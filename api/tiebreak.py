"""
Оркестрация тай-брейка championship: запуск раундов для групп участников,
полностью совпавших по очкам и пропускам (см. scoring.groups_needing_tiebreak),
и их разрешение по мере того, как участники доигрывают общее слово.

Раунд можно разрешить, когда либо все участники доиграли слово, либо наступил
дедлайн (день раунда уже прошёл) — тогда не сыгравшие считаются не угадавшими
за все 6 попыток, как техническое поражение в сетке. Если после разрешения
раунда часть группы всё ещё совпадает — для неё сразу заводится продолжение
(новое слово того же дня, см. create_tiebreak_round), играть можно немедленно.

compute_final_order() восстанавливает итоговый порядок участников по цепочкам
разрешённых раундов — им пользуется генерация сетки плей-офф (api/bracket.py).
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


async def _result_key(session: AsyncSession, entry_id: int, daily_word_id: int) -> tuple[bool, int] | None:
    """(solved, attempts_used) для законченной попытки, иначе None (ещё играет/не начинал)."""
    attempt = await crud.get_attempt(session, entry_id, daily_word_id)
    if attempt is not None and (attempt.solved or attempt.attempts_used >= 6):
        return (attempt.solved, attempt.attempts_used)
    return None


async def _try_resolve_round(session: AsyncSession, tournament: Tournament, round_: TiebreakRound) -> None:
    daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
    deadline_passed = daily_word.calendar_date < today()

    participants = await crud.list_tiebreak_participants(session, round_.id)
    results: dict[int, tuple[bool, int]] = {}
    all_finished = True
    for p in participants:
        key = await _result_key(session, p.entry_id, daily_word.id)
        if key is None:
            all_finished = False
            key = (False, 6)  # используется, только если наступил дедлайн
        results[p.entry_id] = key

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


async def compute_final_order(session: AsyncSession, tournament: Tournament) -> list[int]:
    """
    Итоговый порядок участников championship (лучший первым) после основного
    этапа и, если понадобился, тай-брейка — используется для посева сетки
    плей-офф. Бросает ValueError, если для какой-то группы с равными местами
    тай-брейк ещё не запущен или не разрешился полностью — вызывающий код
    (генерация сетки) не должен сеять розыгрыш с неразрешённой ничьей.
    """
    rows = await compute_standings(session, tournament)

    roots_by_group: dict[frozenset, TiebreakRound] = {}
    for root in await crud.list_root_tiebreak_rounds(session, tournament.id):
        participants = await crud.list_tiebreak_participants(session, root.id)
        roots_by_group[frozenset(p.entry_id for p in participants)] = root

    order: list[int] = []
    seen_places = set()
    for row in rows:
        if row.place in seen_places:
            continue
        seen_places.add(row.place)

        if "-" not in row.place:
            order.append(row.participant_id)
            continue

        group_ids = frozenset(r.participant_id for r in rows if r.place == row.place)
        root = roots_by_group.get(group_ids)
        if root is None:
            raise ValueError(f"Тай-брейк для места {row.place} ещё не запущен")
        order.extend(await _resolve_group_order(session, root))

    return order


async def _resolve_group_order(session: AsyncSession, round_: TiebreakRound) -> list[int]:
    """Порядок участников (лучший первым) для группы, разрешаемой цепочкой
    раундов, начинающейся с round_. Рекурсивно спускается в продолжения."""
    if not round_.completed:
        raise ValueError(f"Раунд тай-брейка #{round_.id} ещё не завершён")

    daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
    participants = await crud.list_tiebreak_participants(session, round_.id)

    keyed: dict[tuple[bool, int], list[int]] = {}
    for p in participants:
        key = await _result_key(session, p.entry_id, daily_word.id) or (False, 6)
        keyed.setdefault(key, []).append(p.entry_id)

    children_by_group = {}
    for child in await crud.get_child_rounds(session, round_.id):
        child_participants = await crud.list_tiebreak_participants(session, child.id)
        children_by_group[frozenset(p.entry_id for p in child_participants)] = child

    # сортировка ключей: сначала решившие, затем по возрастанию числа попыток
    order: list[int] = []
    for key in sorted(keyed.keys(), key=lambda k: (not k[0], k[1])):
        entry_ids = keyed[key]
        if len(entry_ids) == 1:
            order.append(entry_ids[0])
            continue
        child = children_by_group.get(frozenset(entry_ids))
        if child is None:
            raise ValueError(f"Раунд #{round_.id}: часть группы всё ещё равна, но продолжение не найдено")
        order.extend(await _resolve_group_order(session, child))

    return order


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
