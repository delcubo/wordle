"""Админка: марафон: слова и таблица (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import marathon
from api.admin_auth import require_admin
from api.database import get_session
from api.models import TournamentEntry
from api.routers.admin.common import _get_marathon, _tournament_out
from api.schemas import MarathonPlayerWordsOut, MarathonWordOut, SlotLengthRequest, TournamentOut

router = APIRouter()


@router.get("/tournaments/{tournament_id}/marathon/words", response_model=list[MarathonWordOut])
async def get_marathon_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Все слова марафона по порядку; менять (confirm/reroll у /words/{id}) можно те,
    которые никто ещё не начал отгадывать."""
    tournament = await _get_marathon(session, tournament_id)
    if tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона личные наборы слов — см. individual-words")
    return await marathon.words_overview(session, tournament)

@router.post("/tournaments/{tournament_id}/marathon/word-length", response_model=TournamentOut)
async def set_marathon_word_length(
    tournament_id: int, number: int, payload: SlotLengthRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сменить длину слова марафона с номером `number` (query-параметр): слова этой
    позиции, которые никто ещё не начал (у всех участников при личных наборах),
    заменяются словами нужной длины; план длин обновляется."""
    tournament = await _get_marathon(session, tournament_id)
    try:
        await marathon.set_position_length(session, tournament, number, payload.length)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.refresh(tournament)
    return _tournament_out(tournament)

@router.get("/tournaments/{tournament_id}/marathon/individual-words", response_model=list[MarathonPlayerWordsOut])
async def get_marathon_individual_words(
    tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Личные наборы слов всех подключённых участников (если режим личных слов включён)."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона общие слова — см. marathon/words")
    return await marathon.individual_overview(session, tournament)

@router.post("/tournaments/{tournament_id}/marathon/individual-words/regenerate")
async def regenerate_all_individual_words(
    tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Заново подобрать все ещё не начатые слова у всех участников."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона общие слова")
    return {"replaced": await marathon.regenerate_all(session, tournament)}

@router.post("/tournaments/{tournament_id}/marathon/individual-words/{entry_id}/regenerate")
async def regenerate_entry_individual_words(
    tournament_id: int, entry_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Заново подобрать все ещё не начатые слова одного участника."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона общие слова")
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None or entry.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="Участник не найден")
    return {"replaced": await marathon.regenerate_entry_words(session, tournament, entry_id)}
