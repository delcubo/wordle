"""
Оркестрация тай-брейка championship: запуск раундов для групп участников,
полностью совпавших по очкам и пропускам (см. scoring.groups_needing_tiebreak),
и их разрешение по мере того, как участники доигрывают общее слово.

Раунд можно разрешить, когда либо все участники доиграли слово, либо наступил
дедлайн (день раунда уже прошёл) — тогда не сыгравшие считаются не угадавшими
за все 6 попыток, как техническое поражение в сетке. Если после разрешения
раунда часть группы всё ещё совпадает — для неё сразу заводится продолжение
(новое слово того же дня, см. create_tiebreak_round), играть можно немедленно.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentType, TournamentStatus, TiebreakRound
from api.tournament_time import today, day_number_for_date
from api.standings_view import compute_standings
from api.scoring import groups_needing_tiebreak
from api import crud


async def start_tiebreak(session: AsyncSession, tournament: Tournament) -> list[TiebreakRound]:
    """
    Запускается администратором, когда основной этап championship уже прошёл.
    Заводит по TiebreakRound на каждую группу, которой нужен тай-брейк. Если
    таких групп нет, статус розыгрыша не меняется — он уже готов к посеву сетки
    без дополнительных раундов.
    """
    if tournament.type != TournamentType.championship:
        raise ValueError("Тай-брейк применим только к розыгрышам типа championship")
    if tournament.duration_days is None:
        raise ValueError("У этого розыгрыша нет основного этапа с очками")
    day_number = day_number_for_date(tournament.start_date, today())
    if day_number <= tournament.duration_days:
        raise ValueError("Основной этап ещё не завершён")
    if tournament.bracket_size is None:
        raise ValueError("У этого розыгрыша не задан размер сетки плей-офф")
    if await crud.list_tiebreak_rounds(session, tournament.id):
        raise ValueError("Тай-брейк для этого розыгрыша уже запущен")

    rows = await compute_standings(session, tournament)
    groups = groups_needing_tiebreak(rows, tournament.bracket_size)

    rounds = []
    for group in groups:
        entry_ids = [row.participant_id for row in group]
        rounds.append(await crud.create_tiebreak_round(session, tournament, entry_ids))

    if rounds:
        tournament.status = TournamentStatus.tiebreak
        session.add(tournament)
        await session.commit()

    return rounds


async def resolve_ready_rounds(session: AsyncSession, tournament: Tournament) -> None:
    """Проверяет все незавершённые раунды тай-брейка розыгрыша и разрешает те,
    что готовы (см. _try_resolve_round)."""
    for round_ in await crud.list_active_tiebreak_rounds(session, tournament.id):
        await _try_resolve_round(session, tournament, round_)


async def _try_resolve_round(session: AsyncSession, tournament: Tournament, round_: TiebreakRound) -> None:
    daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
    deadline_passed = daily_word.calendar_date < today()

    participants = await crud.list_tiebreak_participants(session, round_.id)
    results: dict[int, tuple[bool, int]] = {}
    all_finished = True
    for p in participants:
        attempt = await crud.get_attempt(session, p.entry_id, daily_word.id)
        if attempt is not None and (attempt.solved or attempt.attempts_used >= 6):
            results[p.entry_id] = (attempt.solved, attempt.attempts_used)
        else:
            all_finished = False
            results[p.entry_id] = (False, 6)  # используется, только если наступил дедлайн

    if not all_finished and not deadline_passed:
        return  # ждём, пока доиграют остальные

    round_.completed = True
    session.add(round_)
    await session.commit()

    still_tied: dict[tuple[bool, int], list[int]] = {}
    for entry_id, key in results.items():
        still_tied.setdefault(key, []).append(entry_id)

    for entry_ids in still_tied.values():
        if len(entry_ids) > 1:
            await crud.create_tiebreak_round(session, tournament, entry_ids, previous_round_id=round_.id)


async def get_rounds_view(session: AsyncSession, tournament_id: int) -> list[dict]:
    """Раунды тай-брейка розыгрыша с расшифровкой участников — для админ-панели."""
    rounds = await crud.list_tiebreak_rounds(session, tournament_id)
    entry_by_id = {e.id: e for e in await crud.list_entries(session, tournament_id)}

    views = []
    for round_ in rounds:
        daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
        participant_views = []
        for p in await crud.list_tiebreak_participants(session, round_.id):
            entry = entry_by_id.get(p.entry_id)
            attempt = await crud.get_attempt(session, p.entry_id, daily_word.id)
            participant_views.append({
                "entry_id": p.entry_id,
                "callsign": entry.callsign if entry else "?",
                "solved": attempt.solved if attempt else None,
                "attempts_used": attempt.attempts_used if attempt else None,
            })
        views.append({
            "id": round_.id,
            "round_number": round_.round_number,
            "previous_round_id": round_.previous_round_id,
            "completed": round_.completed,
            "word": daily_word.word,
            "calendar_date": daily_word.calendar_date,
            "participants": participant_views,
        })
    return views
