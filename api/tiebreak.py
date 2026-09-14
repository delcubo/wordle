"""
Оркестрация тай-брейка — используется в двух режимах:

1. championship: запуск раундов для групп участников, полностью совпавших по
   очкам и пропускам (см. scoring.groups_needing_tiebreak) — start_tiebreak.
2. Розыгрыш типа tiebreak целиком: корневая группа — сразу все подключённые
   участники, раунды начинаются с первого дня розыгрыша — см. ensure_started.

В обоих случаях раунд можно разрешить, когда либо все участники доиграли
слово, либо наступил дедлайн (день раунда уже прошёл). На дедлайне тот, кто
вообще не сделал ни одной попытки, всегда ставится ниже того, кто играл и не
угадал за все 6 — неявка хуже участия, даже неудачного (см. _result_key). Если
после разрешения раунда часть группы всё ещё совпадает — для неё сразу
заводится продолжение (новое слово того же дня, см. create_tiebreak_round),
играть можно немедленно; исключение — если совпадение вызвано тем, что вся
подгруппа не участвовала вовсе: новый раунд тут не поможет (играть некому),
нужна ручная доигровка.

compute_final_order() восстанавливает итоговый порядок участников по цепочкам
разрешённых раундов championship — им пользуется генерация сетки плей-офф
(api/bracket.py). build_results() — аналог для розыгрыша типа tiebreak целиком,
терпимый к ещё не разрешённым раундам (для живого отображения в админке и
игроку — см. get_entry_place).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentType, TournamentStatus, TiebreakRound
from api.tournament_time import today, day_number_for_date
from api.standings_view import compute_standings
from api.scoring import groups_needing_tiebreak
from api.dictionary import pick_alternative_word
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


async def ensure_started(session: AsyncSession, tournament: Tournament) -> None:
    """
    Для розыгрыша типа tiebreak — лениво заводит корневой раунд (сразу все
    подключённые активные участники), как только наступил день старта, точно
    так же, как обычное слово дня лениво заводится у standard/endless (см.
    api/routers/game.py::_resolve_context). Без дополнительного подтверждения
    админом — раунд сразу действующий, играть можно немедленно, как и у
    продолжений раундов championship-тай-брейка.
    """
    if tournament.type != TournamentType.tiebreak:
        return
    if day_number_for_date(tournament.start_date, today()) < 1:
        return
    if await crud.list_root_tiebreak_rounds(session, tournament.id):
        return  # уже запущен
    entries = [e for e in await crud.list_entries(session, tournament.id) if e.active]
    if len(entries) < 2:
        return  # не с кем распределять места — ждём, пока подключат ещё игроков
    await crud.create_tiebreak_round(session, tournament, [e.id for e in entries])


async def resolve_ready_rounds(session: AsyncSession, tournament: Tournament) -> None:
    """Проверяет все незавершённые раунды тай-брейка розыгрыша и разрешает те,
    что готовы (см. _try_resolve_round). Для розыгрыша типа tiebreak целиком —
    после этого сразу проверяет, не разошлись ли уже все места, и если да,
    сам завершает розыгрыш (см. _maybe_finish)."""
    for round_ in await crud.list_active_tiebreak_rounds(session, tournament.id):
        await _try_resolve_round(session, tournament, round_)
    if tournament.type == TournamentType.tiebreak:
        await _maybe_finish(session, tournament)


async def _maybe_finish(session: AsyncSession, tournament: Tournament) -> None:
    """Розыгрыш типа tiebreak завершается сам, как только каждому исходному
    участнику (кто застал самый первый раунд — см. ensure_started) досталось
    единственное, уже не делимое место — по аналогии с авто-финишем сетки на
    вылет при решении финальной пары (см. bracket_game.advance_winner). Игрок,
    подключённый уже после старта (см. пункт бэклога про переброску) и ни разу
    не попавший ни в один раунд, финишу не мешает — распределять для него всё
    равно нечего."""
    if tournament.status == TournamentStatus.finished:
        return
    roots = await crud.list_root_tiebreak_rounds(session, tournament.id)
    if not roots:
        return
    participating_ids: set[int] = set()
    for root in roots:
        participating_ids.update(p.entry_id for p in await crud.list_tiebreak_participants(session, root.id))
    if not participating_ids:
        return

    results = await build_results(session, tournament)
    place_by_entry = {row["entry_id"]: row["place"] for row in results["rows"]}
    if all(
        place_by_entry.get(entry_id) is not None and "-" not in place_by_entry[entry_id]
        for entry_id in participating_ids
    ):
        tournament.status = TournamentStatus.finished
        session.add(tournament)
        await session.commit()


async def build_results(session: AsyncSession, tournament: Tournament) -> dict:
    """
    Сводная таблица для розыгрыша типа tiebreak целиком (см. пункт бэклога):
    список раундов по порядку появления и по каждому участнику — место (число,
    если уже точно определено; диапазон вида "2-4", если группа ещё играет
    дальше или полагающийся ей раунд-продолжение ещё не создан; None, если
    розыгрыш ещё не стартовал) и результат по каждому раунду ("N/6", "X/6" или
    None — не участвовал в этом раунде). В отличие от compute_final_order/
    _resolve_group_order (которые требуют полного разрешения и нужны только
    для посева сетки championship), терпима к ещё не разрешённым раундам —
    для живого отображения в админке и статуса игрока (см. get_entry_place).
    """
    rounds = await crud.list_tiebreak_rounds(session, tournament.id)
    entries = await crud.list_entries(session, tournament.id)

    daily_words = {}
    for r in rounds:
        if r.daily_word_id not in daily_words:
            daily_words[r.daily_word_id] = await crud.get_daily_word_by_id(session, r.daily_word_id)

    participants_by_round: dict[int, list[int]] = {}
    for r in rounds:
        participants_by_round[r.id] = [p.entry_id for p in await crud.list_tiebreak_participants(session, r.id)]

    children_by_round: dict[int, dict[frozenset, TiebreakRound]] = {}
    for r in rounds:
        children_by_round[r.id] = {
            frozenset(participants_by_round[child.id]): child
            for child in await crud.get_child_rounds(session, r.id)
        }

    cells: dict[int, dict[int, dict | None]] = {}
    for r in rounds:
        daily_word = daily_words[r.daily_word_id]
        for entry_id in participants_by_round[r.id]:
            attempt = await crud.get_attempt(session, entry_id, daily_word.id)
            cells.setdefault(entry_id, {})[r.id] = (
                {"solved": attempt.solved, "attempts_used": attempt.attempts_used} if attempt else None
            )

    places: dict[int, str] = {}

    async def walk(round_: TiebreakRound, offset: int) -> int:
        entry_ids = participants_by_round[round_.id]
        size = len(entry_ids)
        if not round_.completed:
            place_str = str(offset + 1) if size == 1 else f"{offset + 1}-{offset + size}"
            for entry_id in entry_ids:
                places[entry_id] = place_str
            return offset + size

        daily_word = daily_words[round_.daily_word_id]
        keyed: dict[tuple, list[int]] = {}
        for entry_id in entry_ids:
            key = await _result_key(session, entry_id, daily_word.id, finalize=True)
            keyed.setdefault(key, []).append(entry_id)

        cur = offset
        for key in sorted(keyed.keys()):
            group = keyed[key]
            if len(group) == 1:
                places[group[0]] = str(cur + 1)
                cur += 1
                continue
            child = children_by_round[round_.id].get(frozenset(group))
            if child is not None:
                cur = await walk(child, cur)
            else:
                place_str = f"{cur + 1}-{cur + len(group)}"
                for entry_id in group:
                    places[entry_id] = place_str
                cur += len(group)
        return cur

    offset = 0
    for root in await crud.list_root_tiebreak_rounds(session, tournament.id):
        offset = await walk(root, offset)

    rows = [
        {
            "entry_id": entry.id,
            "callsign": entry.callsign,
            "active": entry.active,
            "place": places.get(entry.id),
            "cells": [cells.get(entry.id, {}).get(r.id) for r in rounds],
        }
        for entry in entries
    ]

    return {
        "rounds": [
            {"id": r.id, "round_number": r.round_number, "word": daily_words[r.daily_word_id].word, "completed": r.completed}
            for r in rounds
        ],
        "rows": rows,
    }


async def get_entry_place(session: AsyncSession, tournament: Tournament, entry_id: int) -> str | None:
    """Текущее место entry в розыгрыше типа tiebreak — диапазон вида "2-4",
    пока группа ещё не разошлась до конца, точное число, когда место уже не
    изменится, либо None, если розыгрыш ещё не стартовал или entry в нём не
    участвовал (см. build_results)."""
    results = await build_results(session, tournament)
    row = next((r for r in results["rows"] if r["entry_id"] == entry_id), None)
    return row["place"] if row else None


async def reroll_tiebreak_word(session: AsyncSession, tournament: Tournament, day_number: int) -> str:
    """"Предложить другое слово" для ещё не наступившего слота очереди tiebreak
    (см. crud.get_tiebreak_word_queue) — как и у остальных режимов, реролл
    недетерминирован (иначе повторное нажатие всегда возвращало бы то же
    слово)."""
    already_used = await crud.get_all_used_words(session, tournament.id)
    current = (tournament.word_overrides or {}).get(str(day_number))
    new_word = pick_alternative_word(already_used, exclude=current)
    await crud.set_tiebreak_word_override(session, tournament, day_number, new_word)
    return new_word


async def _result_key(
    session: AsyncSession, entry_id: int, daily_word_id: int, *, finalize: bool
) -> tuple[bool, bool, int] | None:
    """
    (не участвовал вовсе, не угадал, число попыток) — меньше значит лучше.
    Участник, который не сделал ни одной попытки, всегда хуже того, кто играл
    и не угадал за все 6 — даже на дедлайне оба не "закончили удачно", но один
    хотя бы принял участие.

    Пока finalize=False, недоигранная попытка (или её полное отсутствие) даёт
    None — сигнал подождать. finalize=True вызывается только после дедлайна и
    всегда возвращает окончательный ключ, засчитывая неявку как участие не
    принявшего и недоигранную попытку как есть (сколько успел).
    """
    attempt = await crud.get_attempt(session, entry_id, daily_word_id)
    if attempt is not None and (attempt.solved or attempt.attempts_used >= 6):
        return (False, not attempt.solved, attempt.attempts_used)
    if not finalize:
        return None
    if attempt is None:
        return (True, True, 6)  # не сделал ни одной попытки — хуже всех
    return (False, True, attempt.attempts_used)  # начал, но не успел доиграть до дедлайна


async def _try_resolve_round(session: AsyncSession, tournament: Tournament, round_: TiebreakRound) -> None:
    daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
    deadline_passed = daily_word.calendar_date < today()

    participants = await crud.list_tiebreak_participants(session, round_.id)
    keys: dict[int, tuple[bool, bool, int] | None] = {}
    all_finished = True
    for p in participants:
        key = await _result_key(session, p.entry_id, daily_word.id, finalize=False)
        if key is None:
            all_finished = False
        keys[p.entry_id] = key

    if not all_finished and not deadline_passed:
        return  # ждём, пока доиграют остальные

    if not all_finished:
        for p in participants:
            if keys[p.entry_id] is None:
                keys[p.entry_id] = await _result_key(session, p.entry_id, daily_word.id, finalize=True)

    round_.completed = True
    session.add(round_)
    await session.commit()

    still_tied: dict[tuple[bool, bool, int], list[int]] = {}
    for entry_id, key in keys.items():
        still_tied.setdefault(key, []).append(entry_id)

    for key, entry_ids in still_tied.items():
        # если ничья только потому, что вся подгруппа вообще не участвовала —
        # новый раунд её не разрешит (играть некому), нужна ручная доигровка
        if len(entry_ids) > 1 and not key[0]:
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
    if round_.manual_order is not None:
        return round_.manual_order  # админ уже назначил порядок вручную — пересчёт не нужен

    if not round_.completed:
        raise ValueError(f"Раунд тай-брейка #{round_.id} ещё не завершён")

    daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
    participants = await crud.list_tiebreak_participants(session, round_.id)

    keyed: dict[tuple[bool, bool, int], list[int]] = {}
    for p in participants:
        # раунд уже завершён, значит финальный ключ для каждого участника уже определён
        key = await _result_key(session, p.entry_id, daily_word.id, finalize=True)
        keyed.setdefault(key, []).append(p.entry_id)

    children_by_group = {}
    for child in await crud.get_child_rounds(session, round_.id):
        child_participants = await crud.list_tiebreak_participants(session, child.id)
        children_by_group[frozenset(p.entry_id for p in child_participants)] = child

    # ключи уже в порядке "меньше — лучше" (False < True), сортировка по кортежу напрямую
    order: list[int] = []
    for key in sorted(keyed.keys()):
        entry_ids = keyed[key]
        if len(entry_ids) == 1:
            order.append(entry_ids[0])
            continue
        child = children_by_group.get(frozenset(entry_ids))
        if child is None:
            raise ValueError(f"Раунд #{round_.id}: часть группы всё ещё равна, но продолжение не найдено")
        order.extend(await _resolve_group_order(session, child))

    return order


async def override_round_order(
    session: AsyncSession, tournament: Tournament, round_: TiebreakRound, order: list[int], note: str
) -> TiebreakRound:
    """
    Ручное назначение порядка участников раунда (например, если он завис —
    никто из подгруппы не сыграл, и новый раунд играть некому). Разрешено
    только пока сетка плей-офф ещё не сгенерирована — иначе порядок мог уже
    повлиять на посев, который задним числом не пересобирается.
    """
    if await crud.list_playoff_matches(session, tournament.id):
        raise ValueError("Сетка плей-офф уже сгенерирована — менять порядок тай-брейка поздно")
    if not note.strip():
        raise ValueError("Нужно указать причину корректировки")

    participants = await crud.list_tiebreak_participants(session, round_.id)
    expected = {p.entry_id for p in participants}
    if set(order) != expected or len(order) != len(expected):
        raise ValueError("Порядок должен содержать ровно всех участников этого раунда, без повторов")

    round_.manual_order = order
    round_.completed = True
    round_.admin_note = note.strip()
    session.add(round_)
    await session.commit()
    await session.refresh(round_)
    return round_


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
            "manual_order": round_.manual_order,
            "admin_note": round_.admin_note,
        })
    return views
