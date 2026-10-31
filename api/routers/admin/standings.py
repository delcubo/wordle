"""Админка: таблица по дням и разбор ничьих (часть api/routers/admin, см. __init__.py)."""

from collections import namedtuple
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, marathon, tiebreak
from api.admin_auth import require_admin
from api.database import get_session
from api.models import Tournament, TournamentEntry, TournamentType
from api.routers.admin.common import _get_marathon
from api.schemas import (
    BonusCellOut,
    DailyCell,
    DayResultOverrideRequest,
    DayResultOverrideResponse,
    MarathonStandingsOut,
    StandingsResponse,
    StandingsRowOut,
    TieGroupMember,
    TieGroupOut,
    TieGroupsResponse,
    TieResolutionsRequest,
)
from api.scoring import calculate_points
from api.standings_view import compute_standings
from api.tournament_time import day_number_for_date, today

router = APIRouter()


@router.get("/tournaments/{tournament_id}/marathon/standings", response_model=MarathonStandingsOut)
async def get_marathon_standings(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Сводная таблица марафона: попытки по каждому слову, пройдено слов, сумма попыток, место."""
    tournament = await _get_marathon(session, tournament_id)
    return await marathon.compute_standings(session, tournament)

@router.get("/tournaments/{tournament_id}/standings", response_model=StandingsResponse)
async def get_standings(
    tournament_id: int, as_of_day: int | None = None,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """
    as_of_day — показать таблицу по состоянию на конкретный уже полностью
    прошедший день (выбор дня в панели — см. пункт бэклога: так админ сам
    решает, копировать ли live-таблицу с ещё не всеми сыгравшими сегодня, или
    зафиксированный снимок прошлого дня). Без as_of_day — обычная live-таблица,
    включает сегодняшний день, если он уже сыгран, как и раньше.

    last_completed_day (в ответе всегда, независимо от as_of_day) — для
    построения списка дней, доступных для выбора на фронте.
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.duration_days is None:
        raise HTTPException(status_code=400, detail="Для этого типа розыгрыша таблица не ведётся")

    raw_day = day_number_for_date(tournament.start_date, today())
    # если розыгрыш уже целиком завершён (сегодня позже последнего дня),
    # завершены все дни; иначе последний завершённый день — вчерашний
    # относительно текущего (сегодняшний ещё идёт)
    last_completed_day = tournament.duration_days if raw_day > tournament.duration_days else max(0, raw_day - 1)

    if as_of_day is not None:
        if as_of_day < 1 or as_of_day > last_completed_day:
            raise HTTPException(status_code=400, detail="Этот день ещё не завершён полностью")
        max_day = as_of_day
        total_days = as_of_day
        current_day = as_of_day
    else:
        max_day = None
        total_days = tournament.duration_days
        current_day = max(1, min(raw_day, tournament.duration_days))

    rows = await compute_standings(session, tournament, max_day=max_day)
    return StandingsResponse(
        rows=[
            StandingsRowOut(
                participant_id=r.participant_id,
                callsign=r.callsign,
                total_points=r.total_points,
                place=r.place,
                tie_resolved=r.tie_resolved,
                daily=[
                    DailyCell(
                        played=d.played, points=d.points, admin_note=d.admin_note,
                        not_played_yet=d.not_played_yet, guesses=d.guesses,
                    )
                    for d in r.daily
                ],
                bonus=[
                    BonusCellOut(
                        number=c["number"], opening_day=c["opening_day"], state=c["state"], points=c["points"],
                        guesses=c["guesses"],
                    )
                    for c in r.bonus
                ],
            )
            for r in rows
        ],
        total_days=total_days,
        current_day=current_day,
        last_completed_day=last_completed_day,
        skip_flag_symbol=tournament.skip_flag_symbol,
        hashtag=tournament.hashtag,
    )

@router.post("/entries/{entry_id}/days/{day_number}/override", response_model=DayResultOverrideResponse)
async def override_day_result(
    entry_id: int, day_number: int, payload: DayResultOverrideRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """
    Ручная корректировка результата дня для одного участника — правит ошибку
    в записи или засчитывает день, который участник не мог сыграть. Таблица
    ничего отдельно не хранит — пересчитывается как обычно, уже с этим Attempt.
    """
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    tournament = await crud.get_tournament(session, entry.tournament_id)
    if tournament is None or tournament.duration_days is None:
        raise HTTPException(status_code=400, detail="Для этого розыгрыша нет дней с очками")
    if day_number < 1 or day_number > tournament.duration_days:
        raise HTTPException(status_code=400, detail=f"День должен быть от 1 до {tournament.duration_days}")
    if not (1 <= payload.attempts_used <= 6):
        raise HTTPException(status_code=400, detail="Число попыток должно быть от 1 до 6")
    note = payload.note.strip()
    if not note:
        raise HTTPException(status_code=400, detail="Нужно указать причину корректировки")

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, day_number)
    points = calculate_points(payload.attempts_used, payload.solved, tournament.scoring_rules)
    attempt = await crud.override_attempt(
        session, entry.id, daily_word.id, payload.attempts_used, payload.solved, points, note
    )
    return DayResultOverrideResponse(
        entry_id=entry.id,
        day_number=day_number,
        attempts_used=attempt.attempts_used,
        solved=attempt.solved,
        points=attempt.points,
        admin_note=attempt.admin_note,
    )

_TieRow = namedtuple("_TieRow", "entry_id callsign place points summary")

async def _tie_groups_view(session: AsyncSession, tournament: Tournament) -> TieGroupsResponse:
    """
    Группы с общим местом в итоговой таблице стандартного розыгрыша или марафона
    (без учёта уже применённых порядков) + для каждой — предложение по результатам
    тай-брейка: розыгрыш типа "Тай-брейк" с в точности теми же игроками
    (сопоставление по человеку, а не по позывному), если он уже расставил все
    места. Нужно для окончательной таблицы без разделённых мест.
    Стандартный разбирается по завершении розыгрыша; марафон — в любой момент
    (устаревший порядок при изменении состава группы просто игнорируется).
    """
    if tournament.type == TournamentType.marathon:
        data = await marathon.compute_standings(session, tournament, apply_tie_resolutions=False)
        rows = [
            _TieRow(
                r["entry_id"], r["callsign"], r["place"], r["score"],
                f"{r['words_done']}/{data['words_count']} слов · {r['score']} попыток",
            )
            for r in data["rows"]
        ]
    elif tournament.type == TournamentType.standard and tournament.duration_days is not None:
        if day_number_for_date(tournament.start_date, today()) <= tournament.duration_days:
            return TieGroupsResponse(can_resolve=False, reason="Розыгрыш ещё не завершён — ничьи разбираются по его итогам")
        rows = [
            _TieRow(r.participant_id, r.callsign, r.place, r.total_points, None)
            for r in await compute_standings(session, tournament, apply_tie_resolutions=False)
        ]
    else:
        return TieGroupsResponse(
            can_resolve=False, reason="Разбор ничьих доступен только для стандартного розыгрыша и марафона"
        )
    entries = {e.id: e for e in await crud.list_entries(session, tournament.id)}
    applied = {frozenset(r["entry_ids"]): r for r in (tournament.tie_resolutions or [])}
    # неархивные тай-брейки первыми (list_tournaments уже идёт от новых к старым)
    tiebreaks = sorted(
        [t for t in await crud.list_tournaments(session) if t.type == TournamentType.tiebreak],
        key=lambda t: t.archived,
    )
    results_cache: dict[int, dict] = {}

    groups: list[TieGroupOut] = []
    seen_places: set[str] = set()
    for row in rows:
        if "-" not in row.place or row.place in seen_places:
            continue
        seen_places.add(row.place)
        member_rows = [r for r in rows if r.place == row.place]
        member_ids = [r.entry_id for r in member_rows]
        user_by_entry = {eid: entries[eid].user_id for eid in member_ids}
        user_set = set(user_by_entry.values())

        group = TieGroupOut(
            place=row.place, points=row.points, summary=row.summary,
            members=[TieGroupMember(entry_id=r.entry_id, callsign=r.callsign) for r in member_rows],
        )

        found = None
        for t in tiebreaks:
            t_entries = await crud.list_entries(session, t.id)
            if {e.user_id for e in t_entries} == user_set:
                found = (t, t_entries)
                break
        if found is None:
            group.suggestion_note = "Подходящий тай-брейк (с тем же составом игроков) не найден — расставьте порядок вручную"
        else:
            t, t_entries = found
            if t.id not in results_cache:
                results_cache[t.id] = await tiebreak.build_results(session, t)
            entry_user = {e.id: e.user_id for e in t_entries}
            place_by_user = {
                entry_user[r["entry_id"]]: r["place"] for r in results_cache[t.id]["rows"] if r["entry_id"] in entry_user
            }
            places = [place_by_user.get(u) for u in user_set]
            if all(p and "-" not in p for p in places) and len(set(places)) == len(places):
                entry_by_user = {user_by_entry[eid]: eid for eid in member_ids}
                ordered_users = sorted(user_set, key=lambda u: int(place_by_user[u]))
                group.suggested_order = [entry_by_user[u] for u in ordered_users]
                group.suggested_source = t.title
            else:
                group.suggestion_note = f"Тай-брейк «{t.title}» ещё не определил все места"

        current = applied.get(frozenset(member_ids))
        if current:
            group.applied_order = current["entry_ids"]
            group.applied_source = current.get("source") or None
        groups.append(group)
    return TieGroupsResponse(can_resolve=True, groups=groups)

@router.get("/tournaments/{tournament_id}/tie-groups", response_model=TieGroupsResponse)
async def get_tie_groups(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    return await _tie_groups_view(session, tournament)

@router.put("/tournaments/{tournament_id}/tie-resolutions", response_model=TieGroupsResponse)
async def put_tie_resolutions(
    tournament_id: int, payload: TieResolutionsRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сохраняет окончательный порядок для групп с общим местом (полностью заменяя
    прежний набор; пустой список — сброс). Каждый порядок должен в точности
    совпадать по составу с одной из текущих групп."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    view = await _tie_groups_view(session, tournament)
    if not view.can_resolve:
        raise HTTPException(status_code=400, detail=view.reason)

    group_sets = {frozenset(m.entry_id for m in g.members) for g in view.groups}
    cleaned: list[dict] = []
    seen: set[frozenset] = set()
    for item in payload.resolutions:
        key = frozenset(item.entry_ids)
        if len(item.entry_ids) != len(key) or key not in group_sets or key in seen:
            raise HTTPException(status_code=400, detail="Порядок не соответствует ни одной из групп с общим местом")
        seen.add(key)
        cleaned.append({"entry_ids": list(item.entry_ids), "source": item.source.strip()[:200]})

    tournament.tie_resolutions = cleaned or None
    session.add(tournament)
    await session.commit()
    return await _tie_groups_view(session, tournament)
