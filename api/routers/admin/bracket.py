"""Админка: сетка плей-офф (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import bracket, bracket_game, crud
from api.admin_auth import require_admin
from api.database import get_session
from api.dictionary import canonical_word, SUPPORTED_LENGTHS, validate_manual_word
from api.models import PlayoffMatch
from api.schemas import (
    BracketRound1Request,
    MatchOverrideRequest,
    PlayoffMatchOut,
    PlayoffWordQueueEntry,
    SetPlayoffWordRequest,
    SlotLengthRequest,
)

router = APIRouter()


def _bracket_response(rows: list[dict]) -> list[PlayoffMatchOut]:
    return [PlayoffMatchOut(**r) for r in rows]

@router.post("/tournaments/{tournament_id}/bracket/generate", response_model=list[PlayoffMatchOut])
async def generate_bracket(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    try:
        await bracket.generate_championship_bracket(session, tournament)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bracket_response(await bracket.get_bracket_view(session, tournament_id))

@router.post("/tournaments/{tournament_id}/bracket/round1", response_model=list[PlayoffMatchOut])
async def set_bracket_round1(
    tournament_id: int, payload: BracketRound1Request,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    try:
        await bracket.set_knockout_round1(session, tournament, payload.pairs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _bracket_response(await bracket.get_bracket_view(session, tournament_id))

@router.get("/tournaments/{tournament_id}/bracket", response_model=list[PlayoffMatchOut])
async def get_bracket(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")

    # тот же лениво-вычисляемый паттерн, что и у тай-брейка: пары с истёкшим
    # дедлайном разрешаются прямо при просмотре админом
    await bracket_game.resolve_ready_matches(session, tournament)

    return _bracket_response(await bracket.get_bracket_view(session, tournament_id))

@router.post("/bracket/matches/{match_id}/override", response_model=PlayoffMatchOut)
async def override_match(
    match_id: int, payload: MatchOverrideRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")
    tournament = await crud.get_tournament(session, match.tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")

    try:
        await bracket_game.override_winner(session, tournament, match, payload.winner_entry_id, payload.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    rows = await bracket.get_bracket_view(session, tournament.id)
    updated = next(r for r in rows if r["id"] == match.id)
    return PlayoffMatchOut(**updated)

@router.get("/bracket/matches/{match_id}/words", response_model=list[PlayoffWordQueueEntry])
async def get_bracket_word_queue(match_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Очередь слов пары (текущее + превью на случай ничьей, WORD_QUEUE_SIZE штук).
    Дальше слова снова генерируются автоматически."""
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")
    return [PlayoffWordQueueEntry(**q) for q in await bracket_game.get_word_queue(session, match)]

@router.post("/bracket/matches/{match_id}/words/{game_number}", response_model=PlayoffWordQueueEntry)
async def set_bracket_word(
    match_id: int, game_number: int, payload: SetPlayoffWordRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    if not 1 <= game_number <= bracket_game.WORD_QUEUE_SIZE:
        raise HTTPException(status_code=400, detail=f"Слово можно задать только для игр 1-{bracket_game.WORD_QUEUE_SIZE} этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    already_used = await crud.get_all_used_words(session, match.tournament_id)
    already_used = already_used | await bracket_game.sibling_queue_words(session, match, game_number)
    error = validate_manual_word(payload.word, already_used)
    if error:
        raise HTTPException(status_code=400, detail=error)
    word = canonical_word(payload.word) or payload.word.strip().lower()

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None:
        if not bracket_game.game_word_editable(existing, match):
            raise HTTPException(status_code=400, detail="Игра уже началась (есть догадки) или закончилась — слово менять поздно")
        await crud.set_playoff_game_word(session, existing, word)
    else:
        await crud.set_playoff_word_override(session, match, game_number, word)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))

@router.post("/bracket/matches/{match_id}/words/{game_number}/length", response_model=PlayoffWordQueueEntry)
async def set_bracket_slot_length(
    match_id: int, game_number: int, payload: SlotLengthRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сменить длину слова слота пары: система подбирает новое слово нужной длины
    (как «Предложить другое», но с выбранной длиной)."""
    if payload.length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина слова должна быть 5, 6 или 7 букв")
    if not 1 <= game_number <= bracket_game.WORD_QUEUE_SIZE:
        raise HTTPException(status_code=400, detail=f"Слово можно задать только для игр 1-{bracket_game.WORD_QUEUE_SIZE} этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None and not bracket_game.game_word_editable(existing, match):
        raise HTTPException(status_code=400, detail="Игра уже началась (есть догадки) или закончилась — слово менять поздно")

    await bracket_game.reroll_word_queue_slot(session, match, game_number, length=payload.length)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))

@router.post("/bracket/matches/{match_id}/words/{game_number}/reroll", response_model=PlayoffWordQueueEntry)
async def reroll_bracket_word(
    match_id: int, game_number: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """"Предложить другое слово" для пары сетки — то же, что реролл обычного
    слова дня, только для слота очереди (см. пункт бэклога)."""
    if not 1 <= game_number <= bracket_game.WORD_QUEUE_SIZE:
        raise HTTPException(status_code=400, detail=f"Слово можно задать только для игр 1-{bracket_game.WORD_QUEUE_SIZE} этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None and not bracket_game.game_word_editable(existing, match):
        raise HTTPException(status_code=400, detail="Игра уже началась (есть догадки) или закончилась — слово менять поздно")

    await bracket_game.reroll_word_queue_slot(session, match, game_number)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))
