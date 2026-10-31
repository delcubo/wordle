"""Админка: бонусные слова (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import bonus, crud
from api.admin_auth import require_admin
from api.database import get_session
from api.dictionary import canonical_word, SUPPORTED_LENGTHS, validate_manual_word
from api.models import Tournament
from api.schemas import BonusWordOut, SetTiebreakWordRequest, SlotLengthRequest

router = APIRouter()


async def _require_bonus_tournament(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if not bonus.supports_bonus(tournament):
        raise HTTPException(status_code=400, detail="Бонусные слова есть только у Стандартного режима и Чемпионата")
    if not tournament.bonus_enabled:
        raise HTTPException(status_code=400, detail="В этом розыгрыше бонусные слова не включены")
    return tournament

async def _bonus_words_out(session: AsyncSession, tournament: Tournament) -> list[BonusWordOut]:
    entries = [e for e in await crud.list_entries(session, tournament.id) if not e.hidden_from_standings]
    states = await bonus.compute_states(session, tournament, entries)
    out = []
    for dw in await bonus.list_bonus_words(session, tournament.id):
        cells = [next(s for s in rows if s["number"] == dw.bonus_number) for rows in states.values()]
        out.append(BonusWordOut(
            number=dw.bonus_number, opening_day=bonus.opening_day(tournament, dw.bonus_number),
            block_start=(dw.bonus_number - 1) * tournament.bonus_every_days + 1,
            calendar_date=dw.calendar_date, word=dw.word, length=len(dw.word), status=dw.status.value,
            editable=not await crud.daily_word_has_attempts(session, dw.id),
            eligible=sum(1 for c in cells if c["state"] in ("played", "open", "expired")),
            played=sum(1 for c in cells if c["state"] == "played"),
        ))
    return out

@router.get("/tournaments/{tournament_id}/bonus-words", response_model=list[BonusWordOut])
async def get_bonus_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await _require_bonus_tournament(session, tournament_id)
    return await _bonus_words_out(session, tournament)

@router.post("/tournaments/{tournament_id}/bonus-words/{number}", response_model=list[BonusWordOut])
async def set_bonus_word(
    tournament_id: int, number: int, payload: SetTiebreakWordRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Своё бонусное слово (пока никто не начал); длина — по самому слову."""
    tournament = await _require_bonus_tournament(session, tournament_id)
    already_used = {w.word for w in await crud.list_daily_words(session, tournament_id, include_bonus=True)
                    if w.bonus_number != number}
    error = validate_manual_word(payload.word, already_used)
    if error:
        raise HTTPException(status_code=400, detail=error)
    try:
        await bonus.set_word(session, tournament, number, canonical_word(payload.word))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _bonus_words_out(session, tournament)

@router.post("/tournaments/{tournament_id}/bonus-words/{number}/reroll", response_model=list[BonusWordOut])
async def reroll_bonus_word(
    tournament_id: int, number: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await _require_bonus_tournament(session, tournament_id)
    try:
        await bonus.reroll_word(session, tournament, number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError:
        raise HTTPException(status_code=400, detail="В словаре не хватает слов для замены")
    return await _bonus_words_out(session, tournament)

@router.post("/tournaments/{tournament_id}/bonus-words/{number}/length", response_model=list[BonusWordOut])
async def set_bonus_word_length(
    tournament_id: int, number: int, payload: SlotLengthRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сменить длину бонусного слова: система подбирает новое слово нужной длины."""
    if payload.length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина слова должна быть 5, 6 или 7 букв")
    tournament = await _require_bonus_tournament(session, tournament_id)
    try:
        await bonus.reroll_word(session, tournament, number, length=payload.length)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError:
        raise HTTPException(status_code=400, detail="В словаре не хватает слов такой длины")
    return await _bonus_words_out(session, tournament)
