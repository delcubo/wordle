"""Админка: команды (марафон, тай-брейк) (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, teams
from api.admin_auth import require_admin
from api.database import get_session
from api.models import Team, Tournament, TournamentEntry, TournamentType
from api.routers.admin.common import _get_marathon, _tournament_out
from api.schemas import (
    EntryOut,
    EntryTeamRequest,
    TeamCreateRequest,
    TeamOut,
    TeamStandingsOut,
    TeamTiebreakCreateRequest,
    TeamTieGroupOut,
    TeamTieGroupsResponse,
    TeamTieMember,
    TeamTieResolutionsRequest,
    TournamentOut,
)
from api.tournament_time import today

router = APIRouter()


async def _team_out(session: AsyncSession, team: Team) -> TeamOut:
    members = [e for e in await crud.list_entries(session, team.tournament_id) if e.team_id == team.id]
    return TeamOut(id=team.id, tournament_id=team.tournament_id, name=team.name, members_count=len(members))

async def _get_team_tournament(session: AsyncSession, tournament_id: int) -> Tournament:
    """Розыгрыш, в котором бывают команды: марафон или тай-брейк."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type not in (TournamentType.marathon, TournamentType.tiebreak):
        raise HTTPException(status_code=400, detail="Команды есть только в марафоне и тай-брейке")
    return tournament

@router.get("/tournaments/{tournament_id}/teams", response_model=list[TeamOut])
async def get_teams(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    await _get_team_tournament(session, tournament_id)
    return [await _team_out(session, t) for t in await teams.list_teams(session, tournament_id)]

@router.post("/tournaments/{tournament_id}/teams", response_model=TeamOut)
async def create_team(
    tournament_id: int, payload: TeamCreateRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await _get_team_tournament(session, tournament_id)
    try:
        team = await teams.create_team(session, tournament, payload.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _team_out(session, team)

@router.patch("/teams/{team_id}", response_model=TeamOut)
async def rename_team(
    team_id: int, payload: TeamCreateRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    try:
        team = await teams.rename_team(session, team, payload.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _team_out(session, team)

@router.delete("/teams/{team_id}")
async def delete_team(team_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Удалить команду: её участники остаются в розыгрыше без команды."""
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    await teams.delete_team(session, team)
    return {"ok": True}

@router.put("/entries/{entry_id}/team", response_model=EntryOut)
async def set_entry_team(
    entry_id: int, payload: EntryTeamRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Поместить участника в команду (team_id=null — убрать из команды). Состав можно менять в
    любой момент: таблица считается на лету."""
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    tournament = await crud.get_tournament(session, entry.tournament_id)
    if tournament is None or tournament.type not in (TournamentType.marathon, TournamentType.tiebreak):
        raise HTTPException(status_code=400, detail="Команды есть только в марафоне и тай-брейке")
    if tournament.type == TournamentType.tiebreak and await crud.list_root_tiebreak_rounds(session, tournament.id):
        raise HTTPException(status_code=400, detail="Тай-брейк уже начался — состав команд менять поздно")
    try:
        return await teams.assign_entry(session, entry, payload.team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/tournaments/{tournament_id}/marathon/team-standings", response_model=TeamStandingsOut)
async def get_team_standings(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Командная таблица марафона: среднее число попыток на слово (api/teams.py)."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.teams_enabled:
        raise HTTPException(status_code=400, detail="В этом марафоне не включён командный зачёт")
    return await teams.compute_team_standings(session, tournament)

async def _team_tie_view(session: AsyncSession, tournament: Tournament) -> TeamTieGroupsResponse:
    if not tournament.teams_enabled:
        return TeamTieGroupsResponse(can_resolve=False, reason="В этом марафоне не включён командный зачёт")
    return TeamTieGroupsResponse(
        can_resolve=True,
        groups=[
            TeamTieGroupOut(**{**g, "members": [TeamTieMember(**m) for m in g["members"]]})
            for g in await teams.tie_groups(session, tournament)
        ],
    )

@router.get("/tournaments/{tournament_id}/team-tie-groups", response_model=TeamTieGroupsResponse)
async def get_team_tie_groups(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await _team_tie_view(session, await _get_marathon(session, tournament_id))

@router.post("/tournaments/{tournament_id}/team-tie-groups/create-tiebreak", response_model=TournamentOut)
async def create_team_tiebreak(
    tournament_id: int, payload: TeamTiebreakCreateRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Создать командный тай-брейк для группы команд с общим местом: новый розыгрыш с теми же
    командами и игроками; потом разбор ничьих сам подскажет порядок по его итогам."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.teams_enabled:
        raise HTTPException(status_code=400, detail="В этом марафоне не включён командный зачёт")
    if payload.start_date is not None and payload.start_date < today():
        raise HTTPException(status_code=400, detail="Дата старта не может быть в прошлом")
    try:
        new = await teams.create_tiebreak_for_group(session, tournament, payload.place, payload.start_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _tournament_out(new)

@router.put("/tournaments/{tournament_id}/team-tie-resolutions", response_model=TeamTieGroupsResponse)
async def put_team_tie_resolutions(
    tournament_id: int, payload: TeamTieResolutionsRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Порядок команд с общим местом (полностью заменяет прежний набор; пустой список — сброс).
    Каждый порядок должен в точности совпадать по составу с одной из текущих групп."""
    tournament = await _get_marathon(session, tournament_id)
    view = await _team_tie_view(session, tournament)
    if not view.can_resolve:
        raise HTTPException(status_code=400, detail=view.reason)
    group_sets = {frozenset(m.team_id for m in g.members) for g in view.groups}
    cleaned: list[dict] = []
    seen: set[frozenset] = set()
    for item in payload.resolutions:
        key = frozenset(item.team_ids)
        if len(item.team_ids) != len(key) or key not in group_sets or key in seen:
            raise HTTPException(status_code=400, detail="Порядок не соответствует ни одной из групп с общим местом")
        seen.add(key)
        cleaned.append({"team_ids": list(item.team_ids), "source": item.source.strip()[:200]})
    tournament.team_tie_resolutions = cleaned or None
    session.add(tournament)
    await session.commit()
    return await _team_tie_view(session, tournament)
