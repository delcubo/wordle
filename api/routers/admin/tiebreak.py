"""Админка: тай-брейк (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, tiebreak
from api.admin_auth import require_admin
from api.database import get_session
from api.dictionary import canonical_word, SUPPORTED_LENGTHS, validate_manual_word
from api.models import TiebreakRound, Tournament, TournamentType
from api.routers.admin.common import _tournament_out
from api.schemas import (
    TournamentOut,
    SetTiebreakWordRequest,
    SlotLengthRequest,
    TeamWordDayOut,
    TiebreakOverrideRequest,
    TiebreakParticipantOut,
    TiebreakReopenRequest,
    TiebreakResultsOut,
    TiebreakRoundOut,
    TiebreakStartResponse,
    TiebreakTeamResultsOut,
    TiebreakWordQueueEntry,
)

router = APIRouter()


@router.post("/tournaments/{tournament_id}/tiebreak/start", response_model=TiebreakStartResponse)
async def start_tiebreak(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    try:
        rounds = await tiebreak.start_tiebreak(session, tournament)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TiebreakStartResponse(started=len(rounds) > 0, rounds_created=len(rounds))

def _tiebreak_round_response(r: dict) -> TiebreakRoundOut:
    return TiebreakRoundOut(
        id=r["id"],
        round_number=r["round_number"],
        previous_round_id=r["previous_round_id"],
        completed=r["completed"],
        word=r["word"],
        calendar_date=r["calendar_date"],
        participants=[TiebreakParticipantOut(**p) for p in r["participants"]],
        manual_order=r["manual_order"],
        admin_note=r["admin_note"],
    )

@router.get("/tournaments/{tournament_id}/tiebreak", response_model=list[TiebreakRoundOut])
async def get_tiebreak_state(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")

    # тот же лениво-вычисляемый паттерн, что и у слова дня: раунды, чей дедлайн
    # уже прошёл, разрешаются прямо при просмотре админом, без фоновых задач
    await tiebreak.resolve_ready_rounds(session, tournament)

    rounds = await tiebreak.get_rounds_view(session, tournament_id)
    return [_tiebreak_round_response(r) for r in rounds]

@router.post("/tournaments/{tournament_id}/tiebreak/reopen", response_model=TournamentOut)
async def reopen_tiebreak(
    tournament_id: int, payload: TiebreakReopenRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Вернуть завершённый тай-брейк в игру, чтобы доиграл тот, кто не успел (см. tiebreak.reopen_tiebreak)."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    try:
        await tiebreak.reopen_tiebreak(session, tournament, payload.end_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.refresh(tournament)
    return _tournament_out(tournament)


@router.post("/tiebreak/rounds/{round_id}/override", response_model=TiebreakRoundOut)
async def override_tiebreak_round(
    round_id: int, payload: TiebreakOverrideRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    round_ = await session.get(TiebreakRound, round_id)
    if round_ is None:
        raise HTTPException(status_code=404, detail="Раунд тай-брейка не найден")
    tournament = await crud.get_tournament(session, round_.tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")

    try:
        await tiebreak.override_round_order(session, tournament, round_, payload.order, payload.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    rounds = await tiebreak.get_rounds_view(session, tournament.id)
    updated = next(r for r in rounds if r["id"] == round_.id)
    return _tiebreak_round_response(updated)

async def _require_tiebreak_tournament(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type != TournamentType.tiebreak:
        raise HTTPException(status_code=400, detail="Этот розыгрыш не типа «тай-брейк»")
    return tournament

def _forbid_team_mode(tournament: Tournament) -> None:
    if crud.is_team_tiebreak(tournament):
        raise HTTPException(status_code=400, detail="В командном тай-брейке слова и результаты — по командам и игрокам (tiebreak-team-*)")

async def _require_team_tiebreak(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await _require_tiebreak_tournament(session, tournament_id)
    if not crud.is_team_tiebreak(tournament):
        raise HTTPException(status_code=400, detail="У этого тай-брейка не включён командный режим")
    return tournament

async def _require_future_day(session: AsyncSession, tournament_id: int, day_number: int) -> None:
    if await crud.get_daily_word_by_day(session, tournament_id, day_number) is not None:
        raise HTTPException(status_code=400, detail="Этот раунд уже наступил — слово менять поздно")

@router.get("/tournaments/{tournament_id}/tiebreak-team-words", response_model=list[TeamWordDayOut])
async def get_tiebreak_team_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Слова командного тай-брейка по раундам и игрокам: у каждого игрока своё слово."""
    tournament = await _require_team_tiebreak(session, tournament_id)
    return [TeamWordDayOut(**q) for q in await tiebreak.get_team_word_queue(session, tournament)]

@router.post("/tournaments/{tournament_id}/tiebreak-team-words/{day_number}/slot/{slot}/sync", response_model=list[TeamWordDayOut])
async def sync_tiebreak_team_slot(
    tournament_id: int, day_number: int, slot: int,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Одно слово на слот: слово k-го игрока первой команды получают k-е игроки всех команд."""
    tournament = await _require_team_tiebreak(session, tournament_id)
    await _require_future_day(session, tournament_id, day_number)
    try:
        await tiebreak.sync_slot_word(session, tournament, day_number, slot)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [TeamWordDayOut(**q) for q in await tiebreak.get_team_word_queue(session, tournament)]

@router.post("/tournaments/{tournament_id}/tiebreak-team-words/{day_number}/{entry_id}", response_model=list[TeamWordDayOut])
async def set_tiebreak_team_word(
    tournament_id: int, day_number: int, entry_id: int, payload: SetTiebreakWordRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await _require_team_tiebreak(session, tournament_id)
    await _require_future_day(session, tournament_id, day_number)
    day = next(q for q in await tiebreak.get_team_word_queue(session, tournament, count=day_number) if q["day_number"] == day_number)
    if all(p["entry_id"] != entry_id for p in day["players"]):
        raise HTTPException(status_code=400, detail="Игрок не участвует в этом раунде")
    already_used = await crud.get_all_used_words(session, tournament_id)
    error = validate_manual_word(payload.word, already_used)
    if error:
        raise HTTPException(status_code=400, detail=error)
    await tiebreak.set_player_word(session, tournament, day_number, entry_id, canonical_word(payload.word))
    return [TeamWordDayOut(**q) for q in await tiebreak.get_team_word_queue(session, tournament)]

@router.post("/tournaments/{tournament_id}/tiebreak-team-words/{day_number}/{entry_id}/reroll", response_model=list[TeamWordDayOut])
async def reroll_tiebreak_team_word(
    tournament_id: int, day_number: int, entry_id: int,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await _require_team_tiebreak(session, tournament_id)
    await _require_future_day(session, tournament_id, day_number)
    try:
        await tiebreak.reroll_player_word(session, tournament, day_number, entry_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [TeamWordDayOut(**q) for q in await tiebreak.get_team_word_queue(session, tournament)]

@router.post("/tournaments/{tournament_id}/tiebreak-team-words/{day_number}/{entry_id}/length", response_model=list[TeamWordDayOut])
async def set_tiebreak_team_word_length(
    tournament_id: int, day_number: int, entry_id: int, payload: SlotLengthRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    if payload.length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина слова должна быть 5, 6 или 7 букв")
    tournament = await _require_team_tiebreak(session, tournament_id)
    await _require_future_day(session, tournament_id, day_number)
    try:
        await tiebreak.reroll_player_word(session, tournament, day_number, entry_id, length=payload.length)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [TeamWordDayOut(**q) for q in await tiebreak.get_team_word_queue(session, tournament)]

@router.get("/tournaments/{tournament_id}/tiebreak-team-results", response_model=TiebreakTeamResultsOut)
async def get_tiebreak_team_results(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await _require_team_tiebreak(session, tournament_id)
    # в отличие от обычного тай-брейка, просмотр НЕ запускает первый раунд: иначе админ, открыв
    # розыгрыш сразу после сборки команд, лишился бы возможности поправить слова и составы.
    # Раунд стартует, когда первый игрок открывает игру (см. game._resolve_context).
    await tiebreak.resolve_ready_rounds(session, tournament)
    results = await tiebreak.build_team_results(session, tournament)
    first_place = tournament.first_place or 1
    teams_played = sum(1 for row in results["rows"] if row["place"] is not None)
    for row in results["rows"]:
        row["place"] = tiebreak.shift_place(row["place"], first_place)
    return TiebreakTeamResultsOut(
        **results, first_place=first_place, last_place=first_place + teams_played - 1 if teams_played else None
    )

@router.get("/tournaments/{tournament_id}/tiebreak-words", response_model=list[TiebreakWordQueueEntry])
async def get_tiebreak_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await _require_tiebreak_tournament(session, tournament_id)
    _forbid_team_mode(tournament)
    queue = await crud.get_tiebreak_word_queue(session, tournament)
    return [TiebreakWordQueueEntry(**q) for q in queue]

@router.post("/tournaments/{tournament_id}/tiebreak-words/{day_number}", response_model=TiebreakWordQueueEntry)
async def set_tiebreak_word(
    tournament_id: int, day_number: int, payload: SetTiebreakWordRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await _require_tiebreak_tournament(session, tournament_id)
    _forbid_team_mode(tournament)
    if await crud.get_daily_word_by_day(session, tournament_id, day_number) is not None:
        raise HTTPException(status_code=400, detail="Этот раунд уже наступил — слово менять поздно")

    already_used = await crud.get_all_used_words(session, tournament_id)
    error = validate_manual_word(payload.word, already_used)
    if error:
        raise HTTPException(status_code=400, detail=error)
    word = canonical_word(payload.word)
    await crud.set_tiebreak_word_override(session, tournament, day_number, word)
    return TiebreakWordQueueEntry(day_number=day_number, word=word, editable=True, length=len(word))

@router.post("/tournaments/{tournament_id}/tiebreak-words/{day_number}/reroll", response_model=TiebreakWordQueueEntry)
async def reroll_tiebreak_word_slot(
    tournament_id: int, day_number: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await _require_tiebreak_tournament(session, tournament_id)
    _forbid_team_mode(tournament)
    if await crud.get_daily_word_by_day(session, tournament_id, day_number) is not None:
        raise HTTPException(status_code=400, detail="Этот раунд уже наступил — слово менять поздно")

    word = await tiebreak.reroll_tiebreak_word(session, tournament, day_number)
    return TiebreakWordQueueEntry(day_number=day_number, word=word, editable=True, length=len(word))

@router.post("/tournaments/{tournament_id}/tiebreak-words/{day_number}/length", response_model=TiebreakWordQueueEntry)
async def set_tiebreak_slot_length(
    tournament_id: int, day_number: int, payload: SlotLengthRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сменить длину слова ещё не наступившего слота очереди тай-брейка: система
    подбирает новое слово нужной длины."""
    if payload.length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина слова должна быть 5, 6 или 7 букв")
    tournament = await _require_tiebreak_tournament(session, tournament_id)
    _forbid_team_mode(tournament)
    if await crud.get_daily_word_by_day(session, tournament_id, day_number) is not None:
        raise HTTPException(status_code=400, detail="Этот раунд уже наступил — слово менять поздно")

    word = await tiebreak.reroll_tiebreak_word(session, tournament, day_number, length=payload.length)
    return TiebreakWordQueueEntry(day_number=day_number, word=word, editable=True, length=len(word))

@router.get("/tournaments/{tournament_id}/tiebreak-results", response_model=TiebreakResultsOut)
async def get_tiebreak_results(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await _require_tiebreak_tournament(session, tournament_id)
    _forbid_team_mode(tournament)
    # тот же лениво-вычисляемый паттерн, что у get_tiebreak_state: заводит
    # корневой раунд, если уже наступил день старта, и разрешает раунды с
    # прошедшим дедлайном — прямо при просмотре, без фоновых задач
    await tiebreak.ensure_started(session, tournament)
    await tiebreak.resolve_ready_rounds(session, tournament)
    results = await tiebreak.build_results(session, tournament)
    # места показываем со сдвигом на первое разыгрываемое место (см. shift_place)
    first_place = tournament.first_place or 1
    players = sum(1 for row in results["rows"] if row["place"] is not None)
    for row in results["rows"]:
        row["place"] = tiebreak.shift_place(row["place"], first_place)
    return TiebreakResultsOut(
        **results, first_place=first_place, last_place=first_place + players - 1 if players else None
    )
