"""Админка: слово дня (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud
from api.admin_auth import require_admin
from api.database import get_session
from api.dictionary import canonical_word, validate_manual_word
from api.models import TournamentType
from api.modes import has as mode_has
from api.schemas import ConfirmWordRequest, DailyWordOut
from api.tournament_time import day_number_for_date, today

router = APIRouter()


@router.get("/tournaments/{tournament_id}/words", response_model=list[DailyWordOut])
async def get_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await crud.list_daily_words(session, tournament_id)

@router.get("/tournaments/{tournament_id}/words/upcoming", response_model=DailyWordOut)
async def get_upcoming_word(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """
    Слово на ближайший ещё не наступивший день — то, что админ может подтвердить
    или заменить. Работает и для endless (там просто нет верхней границы дней —
    см. пункт бэклога), но не для knockout — там нет слова дня вне пар сетки, и
    не для tiebreak — там день не календарный, а раундовый (см. crud.get_tiebreak_word_queue),
    и предсоздание "завтрашнего" слова тут сбило бы нумерацию дней раундов.
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if not mode_has(tournament.type, "daily_words"):
        raise HTTPException(status_code=400, detail="У этого типа розыгрыша нет ежедневного слова")

    current_day = day_number_for_date(tournament.start_date, today())
    next_day = max(current_day, 0) + 1  # ближайший день, который ещё не наступил
    if tournament.duration_days is not None and next_day > tournament.duration_days:
        raise HTTPException(status_code=400, detail="Розыгрыш уже завершается — новых дней не осталось")

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, next_day)
    return daily_word

@router.get("/tournaments/{tournament_id}/words/today", response_model=DailyWordOut)
async def get_today_word(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """
    Слово сегодняшнего (уже идущего) дня — чисто для справки админу (см. пункт
    #3 бэклога: "upcoming" всегда прыгает на день вперёд и никогда не показывает
    день, который уже наступил, включая самый первый день розыгрыша). Менять
    слово можно только в бессрочной игре и пока никто не начал партию (editable).
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if not mode_has(tournament.type, "daily_words"):
        raise HTTPException(status_code=400, detail="У этого типа розыгрыша нет слова дня")

    current_day = day_number_for_date(tournament.start_date, today())
    if current_day < 1:
        raise HTTPException(status_code=400, detail="Розыгрыш ещё не начался")
    if tournament.duration_days is not None and current_day > tournament.duration_days:
        raise HTTPException(status_code=400, detail="Розыгрыш уже завершился")

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, current_day)
    out = DailyWordOut.model_validate(daily_word)
    out.editable = await _daily_word_editable(session, daily_word)
    return out

async def _daily_word_editable(session: AsyncSession, daily_word) -> bool:
    """Слово можно менять до наступления его дня. В бессрочной и стандартной
    играх — ещё и в сам день, пока никто не начал партию (слово игроку не
    показывается до конца партии, поэтому без единой догадки замена ничего не
    ломает)."""
    tournament = await crud.get_tournament(session, daily_word.tournament_id)
    if tournament is not None and tournament.type == TournamentType.marathon:
        # слова марафона нет смысла привязывать к дате: меняется, пока его никто не начал
        return not await crud.daily_word_has_attempts(session, daily_word.id)
    if daily_word.calendar_date > today():
        return True
    if daily_word.calendar_date < today():
        return False
    if tournament is None or tournament.type not in (TournamentType.endless, TournamentType.standard):
        return False
    return not await crud.daily_word_has_attempts(session, daily_word.id)

async def _word_locked_detail(session: AsyncSession, daily_word) -> str:
    tournament = await crud.get_tournament(session, daily_word.tournament_id)
    if tournament is not None and tournament.type == TournamentType.marathon:
        return "Это слово уже начали отгадывать — менять поздно"
    return "Этот день уже наступил — слово менять поздно"

@router.post("/words/{daily_word_id}/confirm", response_model=DailyWordOut)
async def confirm_word(
    daily_word_id: int, payload: ConfirmWordRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    from api.models import DailyWord
    daily_word = await session.get(DailyWord, daily_word_id)
    if daily_word is None:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    if not await _daily_word_editable(session, daily_word):
        raise HTTPException(status_code=400, detail=await _word_locked_detail(session, daily_word))

    if payload.override_word:
        # в личных наборах марафона повтор слова ДРУГОГО участника допустим — запрещён только повтор внутри набора
        already_used = {
            w.word for w in await crud.list_daily_words(session, daily_word.tournament_id, include_bonus=True)
            if w.id != daily_word.id and w.entry_id == daily_word.entry_id
        }
        error = validate_manual_word(payload.override_word, already_used)
        if error:
            raise HTTPException(status_code=400, detail=error)
        # приводим к каноническому написанию из словаря (с ё, если оно там есть) —
        # админ мог набрать вариант с е, см. dictionary.canonical_word
        override = canonical_word(payload.override_word)
    else:
        override = None

    return await crud.confirm_daily_word(session, daily_word, override)

@router.post("/words/{daily_word_id}/reroll", response_model=DailyWordOut)
async def reroll_word(
    daily_word_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    from api.models import DailyWord
    daily_word = await session.get(DailyWord, daily_word_id)
    if daily_word is None:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    if not await _daily_word_editable(session, daily_word):
        raise HTTPException(status_code=400, detail=await _word_locked_detail(session, daily_word))

    return await crud.reroll_daily_word(session, daily_word)
