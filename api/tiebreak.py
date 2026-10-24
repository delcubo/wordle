"""
Оркестрация тай-брейка — используется в двух режимах:

1. championship: запуск раундов для групп участников, полностью совпавших по
   очкам и пропускам (см. scoring.groups_needing_tiebreak) — start_tiebreak.
2. Розыгрыш типа tiebreak целиком: корневая группа — сразу все подключённые
   участники, раунды начинаются с первого дня розыгрыша — см. ensure_started.

В обоих случаях раунд можно разрешить, когда либо все участники доиграли
слово, либо наступил дедлайн (день раунда уже прошёл). На дедлайне тот, кто
вообще не сделал ни одной попытки, всегда ставится ниже того, кто играл и не
угадал за все 6 — пропуск хуже провала (см. _result_key и api/attempt_scores.py). Если
после разрешения раунда часть группы всё ещё совпадает — для неё сразу
заводится продолжение (новое слово того же дня, см. create_tiebreak_round),
играть можно немедленно; исключение — если совпадение вызвано тем, что вся
подгруппа не участвовала вовсе: новый раунд тут не поможет (играть некому),
нужна ручная доигровка.

Командный тай-брейк (тип tiebreak + Tournament.teams_enabled, см. api/teams.py): игроки
объединены в команды, у каждого игрока раунда СВОЁ слово (все разные — подсказывать друг
другу нечего), а место определяют команды. Результат команды в раунде — среднее по её
игрокам: угадал — число попыток, не угадал (все 6 попыток) — 7, не завершил слово или не
приступал к нему — 8 (пропуск хуже провала). Одинаковое среднее (точное сравнение) —
продолжение раунда для этих команд с новыми личными словами; если среднее равно 8, то
никто из них не играл, и продолжение не заводится (как и у обычного тай-брейка).

compute_final_order() восстанавливает итоговый порядок участников по цепочкам
разрешённых раундов championship — им пользуется генерация сетки плей-офф
(api/bracket.py). build_results() — аналог для розыгрыша типа tiebreak целиком,
терпимый к ещё не разрешённым раундам (для живого отображения в админке и
игроку — см. get_entry_place).
"""
from collections import defaultdict
from fractions import Fraction

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import (
    Tournament, TournamentType, TournamentStatus, TiebreakRound, TiebreakParticipant, DailyWord, TournamentEntry, Attempt,
)
from api.tournament_time import today, day_number_for_date
from api.standings_view import compute_standings
from api.scoring import groups_needing_tiebreak
from api.dictionary import pick_alternative_word
from api.word_plan import tiebreak_length
from api import crud
from api.attempt_scores import FAILED_ATTEMPTS, SKIPPED_ATTEMPTS


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
    if crud.is_team_tiebreak(tournament):
        entries = await team_participants(session, tournament)
        if len({e.team_id for e in entries}) < 2:
            return  # нужно хотя бы две команды (в каждой не меньше MIN_TEAM_SIZE подключённых игроков)
        await crud.create_tiebreak_round(session, tournament, [e.id for e in entries])
        return
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
        if crud.is_team_tiebreak(tournament):
            await _try_resolve_team_round(session, tournament, round_)
        else:
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
    if crud.is_team_tiebreak(tournament):
        team_ids: set[int] = set()
        for root in roots:
            team_ids.update(p.team_id for p in await crud.list_tiebreak_participants(session, root.id) if p.team_id)
        if not team_ids:
            return
        team_results = await build_team_results(session, tournament)
        place_by_team = {row["team_id"]: row["place"] for row in team_results["rows"]}
        if all(place_by_team.get(tid) is not None and "-" not in place_by_team[tid] for tid in team_ids):
            tournament.status = TournamentStatus.finished
            session.add(tournament)
            await session.commit()
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


def shift_place(place: str | None, first_place: int | None) -> str | None:
    """Место для показа с учётом того, с какого места разыгрывается тай-брейк
    (Tournament.first_place): "2" -> "14", "2-3" -> "14-15" при first_place=13.
    Внутренний расчёт остаётся по относительным местам — сдвигается только то,
    что показываем админу и игрокам."""
    offset = (first_place or 1) - 1
    if not place or offset == 0:
        return place
    parts = place.split("-")
    return "-".join(str(int(p) + offset) for p in parts)


async def get_entry_place(session: AsyncSession, tournament: Tournament, entry_id: int) -> str | None:
    """Текущее место entry в розыгрыше типа tiebreak — диапазон вида "2-4",
    пока группа ещё не разошлась до конца, точное число, когда место уже не
    изменится, либо None, если розыгрыш ещё не стартовал или entry в нём не
    участвовал (см. build_results). В командном тай-брейке — место команды игрока."""
    if crud.is_team_tiebreak(tournament):
        results = await build_team_results(session, tournament)
        row = next((r for r in results["rows"] if any(m["entry_id"] == entry_id for m in r["members"])), None)
        return row["place"] if row else None
    results = await build_results(session, tournament)
    row = next((r for r in results["rows"] if r["entry_id"] == entry_id), None)
    return row["place"] if row else None


async def reroll_tiebreak_word(
    session: AsyncSession, tournament: Tournament, day_number: int, length: int | None = None
) -> str:
    """"Предложить другое слово" для ещё не наступившего слота очереди tiebreak
    (см. crud.get_tiebreak_word_queue) — как и у остальных режимов, реролл
    недетерминирован (иначе повторное нажатие всегда возвращало бы то же
    слово)."""
    already_used = await crud.get_all_used_words(session, tournament.id)
    current = (tournament.word_overrides or {}).get(str(day_number))
    if length is None:  # по умолчанию длина слота сохраняется
        length = len(current) if current else tiebreak_length(tournament, day_number)
    new_word = pick_alternative_word(already_used, exclude=current, length=length)
    await crud.set_tiebreak_word_override(session, tournament, day_number, new_word)
    return new_word


def round_deadline_passed(tournament: Tournament, anchor: DailyWord) -> bool:
    """Вышел ли срок раунда. По умолчанию раунд закрывается в конце своего дня; если у тай-брейка
    задана дата окончания (Tournament.end_date) — в конце этого дня, но не раньше дня самого раунда
    (продолжение, заведённое уже после даты окончания, живёт свой день, а не умирает сразу)."""
    last_day = anchor.calendar_date
    if tournament.type == TournamentType.tiebreak and tournament.end_date is not None:
        last_day = max(last_day, tournament.end_date)
    return last_day < today()


async def _result_key(
    session: AsyncSession, entry_id: int, daily_word_id: int, *, finalize: bool
) -> int | None:
    """
    Очки игрока за слово тай-брейка по единой лестнице (api/attempt_scores.py), меньше — лучше:
    угадал — число попыток (1-6), использовал все 6 попыток и не угадал — FAILED_ATTEMPTS (7),
    не завершил слово или не приступал к нему — SKIPPED_ATTEMPTS (8). Провал всегда лучше
    пропуска: игроку выгоднее доиграть до конца.

    Пока finalize=False, недоигранная попытка (или её полное отсутствие) даёт None — сигнал
    подождать. finalize=True вызывается только после дедлайна и всегда возвращает окончательный
    результат: всё, что не завершено к дедлайну, — пропуск.
    """
    attempt = await crud.get_attempt(session, entry_id, daily_word_id)
    if attempt is not None and (attempt.solved or attempt.attempts_used >= 6):
        return attempt.attempts_used if attempt.solved else FAILED_ATTEMPTS
    if not finalize:
        return None
    return SKIPPED_ATTEMPTS


async def _try_resolve_round(session: AsyncSession, tournament: Tournament, round_: TiebreakRound) -> None:
    daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
    deadline_passed = round_deadline_passed(tournament, daily_word)

    participants = await crud.list_tiebreak_participants(session, round_.id)
    keys: dict[int, int | None] = {}
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

    still_tied: dict[int, list[int]] = {}
    for entry_id, key in keys.items():
        still_tied.setdefault(key, []).append(entry_id)

    for key, entry_ids in still_tied.items():
        # если ничья только потому, что вся подгруппа пропустила слово (не завершила или не
        # приступала) — новый раунд её не разрешит (играть некому), нужна ручная доигровка
        if len(entry_ids) > 1 and key != SKIPPED_ATTEMPTS:
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


# ---------- Командный тай-брейк ----------

async def team_participants(session: AsyncSession, tournament: Tournament) -> list[TournamentEntry]:
    """Игроки, с которых начинается командный тай-брейк: подключённые игроки команд, в которых
    таких игроков не меньше MIN_TEAM_SIZE (игроки вне команд и команды из одного не играют)."""
    from api.teams import MIN_TEAM_SIZE
    by_team: dict[int, list[TournamentEntry]] = defaultdict(list)
    for entry in await crud.list_entries(session, tournament.id):
        if entry.active and entry.team_id is not None:
            by_team[entry.team_id].append(entry)
    return [e for members in by_team.values() if len(members) >= MIN_TEAM_SIZE for e in members]


async def word_for_entry(session: AsyncSession, round_: TiebreakRound, entry_id: int) -> DailyWord:
    """Слово игрока в раунде тай-брейка: личное (командный) либо общее слово раунда."""
    return await crud.get_daily_word_by_id(session, await crud.round_word_id_for_entry(session, round_, entry_id))


def _team_scores(participants, keys: dict[int, int]) -> dict[int, Fraction]:
    """Среднее команды в раунде: очки игроков (попытки / 7 / 8) по единой лестнице."""
    scores: dict[int, list[int]] = defaultdict(list)
    for p in participants:
        scores[p.team_id].append(keys[p.entry_id])
    return {team_id: Fraction(sum(values), len(values)) for team_id, values in scores.items()}


async def _try_resolve_team_round(session: AsyncSession, tournament: Tournament, round_: TiebreakRound) -> None:
    anchor = await crud.get_daily_word_by_id(session, round_.daily_word_id)
    deadline_passed = round_deadline_passed(tournament, anchor)

    participants = await crud.list_tiebreak_participants(session, round_.id)
    keys: dict[int, int | None] = {}
    all_finished = True
    for p in participants:
        key = await _result_key(session, p.entry_id, p.daily_word_id, finalize=False)
        if key is None:
            all_finished = False
        keys[p.entry_id] = key

    if not all_finished and not deadline_passed:
        return  # ждём, пока доиграют остальные

    if not all_finished:
        for p in participants:
            if keys[p.entry_id] is None:
                keys[p.entry_id] = await _result_key(session, p.entry_id, p.daily_word_id, finalize=True)

    round_.completed = True
    session.add(round_)
    await session.commit()

    by_score: dict[Fraction, list[int]] = defaultdict(list)
    for team_id, score in _team_scores(participants, keys).items():
        by_score[score].append(team_id)
    for score, team_ids in by_score.items():
        # среднее 8 — все игроки этих команд пропустили слово: новый раунд играть некому
        if len(team_ids) > 1 and score != SKIPPED_ATTEMPTS:
            entry_ids = [p.entry_id for p in participants if p.team_id in team_ids]
            await crud.create_tiebreak_round(session, tournament, entry_ids, previous_round_id=round_.id)


async def build_team_results(session: AsyncSession, tournament: Tournament) -> dict:
    """Сводная таблица командного тай-брейка: раунды и по каждой команде — место (число, диапазон
    «2-3», пока команды ещё играют дальше или продолжение не заведено, либо None, если команда ещё
    не участвовала), среднее по каждому завершённому раунду и результаты её игроков."""
    from api import teams as teams_module
    rounds = await crud.list_tiebreak_rounds(session, tournament.id)
    entries = {e.id: e for e in await crud.list_entries(session, tournament.id)}
    team_by_id = {t.id: t for t in await teams_module.list_teams(session, tournament.id)}

    participants_by_round = {r.id: await crud.list_tiebreak_participants(session, r.id) for r in rounds}
    children_by_round: dict[int, dict[frozenset, TiebreakRound]] = {}
    for r in rounds:
        children_by_round[r.id] = {
            frozenset(p.entry_id for p in participants_by_round[child.id]): child
            for child in await crud.get_child_rounds(session, r.id)
        }

    member_cells: dict[int, dict[int, dict | None]] = defaultdict(dict)   # entry -> round -> результат
    keys_by_round: dict[int, dict[int, int]] = {}
    for r in rounds:
        keys_by_round[r.id] = {}
        for p in participants_by_round[r.id]:
            attempt = await crud.get_attempt(session, p.entry_id, p.daily_word_id)
            member_cells[p.entry_id][r.id] = (
                {"solved": attempt.solved, "attempts_used": attempt.attempts_used} if attempt else None
            )
            if r.completed:
                keys_by_round[r.id][p.entry_id] = await _result_key(session, p.entry_id, p.daily_word_id, finalize=True)

    scores_by_round = {
        r.id: _team_scores(participants_by_round[r.id], keys_by_round[r.id]) for r in rounds if r.completed
    }

    places: dict[int, str] = {}

    async def walk(round_: TiebreakRound, offset: int) -> int:
        parts = participants_by_round[round_.id]
        team_ids = sorted({p.team_id for p in parts})
        if not round_.completed:
            place_str = str(offset + 1) if len(team_ids) == 1 else f"{offset + 1}-{offset + len(team_ids)}"
            for team_id in team_ids:
                places[team_id] = place_str
            return offset + len(team_ids)
        by_score: dict[Fraction, list[int]] = defaultdict(list)
        for team_id, score in scores_by_round[round_.id].items():
            by_score[score].append(team_id)
        cur = offset
        for score in sorted(by_score):
            group = by_score[score]
            if len(group) == 1:
                places[group[0]] = str(cur + 1)
                cur += 1
                continue
            group_entries = frozenset(p.entry_id for p in parts if p.team_id in group)
            child = children_by_round[round_.id].get(group_entries)
            if child is not None:
                cur = await walk(child, cur)
            else:
                place_str = f"{cur + 1}-{cur + len(group)}"
                for team_id in group:
                    places[team_id] = place_str
                cur += len(group)
        return cur

    offset = 0
    for root in await crud.list_root_tiebreak_rounds(session, tournament.id):
        offset = await walk(root, offset)

    rows = []
    for team_id, team in sorted(team_by_id.items()):
        member_ids = {e.id for e in entries.values() if e.team_id == team_id}
        for r in rounds:
            member_ids.update(p.entry_id for p in participants_by_round[r.id] if p.team_id == team_id)
        team_cells = []
        for r in rounds:
            in_round = any(p.team_id == team_id for p in participants_by_round[r.id])
            if in_round and r.completed:
                score = scores_by_round[r.id][team_id]
                team_cells.append({"average": teams_module._format(score, 2), "average_value": float(score)})
            else:
                team_cells.append(None)
        rows.append({
            "team_id": team_id, "name": team.name, "place": places.get(team_id), "cells": team_cells,
            "members": [
                {
                    "entry_id": eid, "callsign": entries[eid].callsign if eid in entries else "?",
                    "active": entries[eid].active if eid in entries else False,
                    "cells": [member_cells.get(eid, {}).get(r.id) for r in rounds],
                }
                for eid in sorted(member_ids, key=lambda i: entries[i].callsign.lower() if i in entries else "")
            ],
        })
    rows.sort(key=lambda r: (r["place"] is None, [int(x) for x in r["place"].split("-")] if r["place"] else [0], r["name"].lower()))
    return {
        "rounds": [{"id": r.id, "round_number": r.round_number, "completed": r.completed} for r in rounds],
        "rows": rows,
    }


# Слова игроков командного тай-брейка (превью очереди + ручные правки админа)

async def get_team_word_queue(session: AsyncSession, tournament: Tournament, count: int = 5) -> list[dict]:
    """Очередь слов командного тай-брейка по раундам (номерам дня) и игрокам: для ещё не наступивших
    раундов — слова по сиду (или ручная замена), как только раунд создан — реальные слова, без
    правки. Игроки превью — те, с кого начинается тай-брейк (team_participants); slot — номер
    игрока в своей команде (по порядку подключения)."""
    words = await crud.list_daily_words(session, tournament.id)
    anchors = {w.day_number for w in words if w.entry_id is None}
    personal: dict[int, dict[int, DailyWord]] = defaultdict(dict)
    for w in words:
        if w.entry_id is not None:
            personal[w.day_number][w.entry_id] = w

    entries = {e.id: e for e in await crud.list_entries(session, tournament.id)}
    from api import teams as teams_module
    team_by_id = {t.id: t for t in await teams_module.list_teams(session, tournament.id)}
    preview_entries = await team_participants(session, tournament)
    already_used = await crud._get_used_words(session, tournament.id)

    def player_row(entry_id: int, word: str, editable: bool, slot_of: dict[int, int]) -> dict:
        entry = entries.get(entry_id)
        team = team_by_id.get(entry.team_id) if entry else None
        return {
            "entry_id": entry_id, "callsign": entry.callsign if entry else "?",
            "team_id": team.id if team else None, "team_name": team.name if team else None,
            "slot": slot_of.get(entry_id, 0), "word": word, "length": len(word), "editable": editable,
        }

    queue = []
    for day in range(1, count + 1):
        if day in anchors:
            day_entries = [entries[eid] for eid in personal[day] if eid in entries]
            slot_of = _slots(day_entries)
            players = [player_row(eid, personal[day][eid].word, False, slot_of) for eid in
                       sorted(personal[day], key=lambda i: (entries[i].team_id or 0, i) if i in entries else (0, i))]
            queue.append({"day_number": day, "editable": False, "players": players})
            continue
        picked = crud.pick_team_round_words(tournament, day, day, preview_entries, already_used)
        slot_of = _slots(preview_entries)
        players = [player_row(e.id, picked[e.id], True, slot_of) for e in sorted(preview_entries, key=lambda e: (e.team_id, e.id))]
        queue.append({"day_number": day, "editable": True, "players": players})
    return queue


def _slots(entries: list) -> dict[int, int]:
    """entry_id -> номер игрока в своей команде (1, 2, ...) по порядку id."""
    by_team: dict[int, list[int]] = defaultdict(list)
    for e in entries:
        by_team[e.team_id].append(e.id)
    return {eid: i + 1 for ids in by_team.values() for i, eid in enumerate(sorted(ids))}


async def _queue_day(session: AsyncSession, tournament: Tournament, day_number: int) -> dict:
    queue = await get_team_word_queue(session, tournament, count=max(day_number, 1))
    return next(q for q in queue if q["day_number"] == day_number)


async def set_player_word(session: AsyncSession, tournament: Tournament, day_number: int, entry_id: int, word: str) -> None:
    overrides = dict(tournament.word_overrides or {})
    overrides[crud.team_override_key(day_number, entry_id)] = word
    tournament.word_overrides = overrides
    session.add(tournament)
    await session.commit()


async def reroll_player_word(
    session: AsyncSession, tournament: Tournament, day_number: int, entry_id: int, length: int | None = None
) -> str:
    """«Предложить другое» для слова игрока в ещё не наступившем раунде; слово не повторяет уже
    использованные и слова остальных игроков этого раунда. По умолчанию длина сохраняется."""
    from api.dictionary import pick_alternative_word
    day = await _queue_day(session, tournament, day_number)
    current = next((p for p in day["players"] if p["entry_id"] == entry_id), None)
    if current is None:
        raise ValueError("Игрок не участвует в этом раунде")
    used = await crud.get_all_used_words(session, tournament.id) | {p["word"] for p in day["players"]}
    new_word = pick_alternative_word(used, exclude=current["word"], length=length or current["length"])
    await set_player_word(session, tournament, day_number, entry_id, new_word)
    return new_word


async def sync_slot_word(session: AsyncSession, tournament: Tournament, day_number: int, slot: int) -> str:
    """Одно слово на слот: слово k-го игрока первой команды становится словом k-го игрока каждой
    команды (так все команды решают один набор слов — как в варианте «по слотам»)."""
    day = await _queue_day(session, tournament, day_number)
    in_slot = [p for p in day["players"] if p["slot"] == slot]
    if not in_slot:
        raise ValueError("В этом раунде нет игроков с таким номером в команде")
    word = in_slot[0]["word"]
    overrides = dict(tournament.word_overrides or {})
    for p in in_slot:
        overrides[crud.team_override_key(day_number, p["entry_id"])] = word
    tournament.word_overrides = overrides
    session.add(tournament)
    await session.commit()
    return word


# ---------- Удаление игрока из тай-брейка ----------

async def _tie_groups_of_round(session: AsyncSession, tournament: Tournament, round_: TiebreakRound) -> list[frozenset]:
    """Группы участников (наборы entry_id) завершённого раунда, которым по текущим результатам
    нужно продолжение: равные результаты игроков (обычный тай-брейк) либо равное среднее команд
    (командный; в группу входят все игроки этих команд). Пропустившие слово (8) продолжения не получают."""
    participants = await crud.list_tiebreak_participants(session, round_.id)
    if not participants:
        return []
    keys = {}
    for p in participants:
        keys[p.entry_id] = await _result_key(session, p.entry_id, p.daily_word_id or round_.daily_word_id, finalize=True)
    groups: list[frozenset] = []
    if crud.is_team_tiebreak(tournament):
        by_score: dict[Fraction, list[int]] = defaultdict(list)
        for team_id, score in _team_scores(participants, keys).items():
            by_score[score].append(team_id)
        for score, team_ids in by_score.items():
            if len(team_ids) > 1 and score != SKIPPED_ATTEMPTS:
                groups.append(frozenset(p.entry_id for p in participants if p.team_id in team_ids))
    else:
        by_key: dict[int, list[int]] = defaultdict(list)
        for entry_id, key in keys.items():
            by_key[key].append(entry_id)
        for key, entry_ids in by_key.items():
            if len(entry_ids) > 1 and key != SKIPPED_ATTEMPTS:
                groups.append(frozenset(entry_ids))
    return groups


async def _delete_round(session: AsyncSession, round_id: int) -> None:
    """Удаляет раунд вместе с продолжениями, его словами и попытками по ним."""
    round_ = await session.get(TiebreakRound, round_id)
    if round_ is None:
        return
    anchor_id = round_.daily_word_id  # до рекурсии: она сбрасывает кэш сессии (expire_all)
    for child in await crud.get_child_rounds(session, round_id):
        await _delete_round(session, child.id)
    participants = await crud.list_tiebreak_participants(session, round_id)
    word_ids = {p.daily_word_id for p in participants if p.daily_word_id} | {anchor_id}
    await session.execute(delete(TiebreakParticipant).where(TiebreakParticipant.round_id == round_id))
    await session.execute(delete(TiebreakRound).where(TiebreakRound.id == round_id))
    await session.execute(delete(Attempt).where(Attempt.daily_word_id.in_(word_ids)))
    await session.execute(delete(DailyWord).where(DailyWord.id.in_(word_ids)))
    await session.commit()
    session.expire_all()


async def reconcile_rounds(session: AsyncSession, tournament: Tournament) -> None:
    """Приводит цепочки раундов в соответствие с текущими результатами: продолжение, которое больше
    не нужно (ничья распалась), удаляется, а для новой ничьи заводится недостающее. Нужно после
    удаления игрока, когда результаты и средние команд пересчитываются."""
    tournament_id = tournament.id
    session.expire_all()
    ids = sorted((r.round_number, r.id) for r in await crud.list_tiebreak_rounds(session, tournament_id))
    for _, round_id in ids:
        tournament = await crud.get_tournament(session, tournament_id)  # после expire_all — заново
        round_ = await session.get(TiebreakRound, round_id)
        if round_ is None or not round_.completed or round_.manual_order is not None:
            continue
        valid = set(await _tie_groups_of_round(session, tournament, round_))
        existing: set[frozenset] = set()
        for child in await crud.get_child_rounds(session, round_id):
            members = frozenset(p.entry_id for p in await crud.list_tiebreak_participants(session, child.id))
            if members in valid:
                existing.add(members)
            else:
                await _delete_round(session, child.id)
        for group in valid - existing:
            await crud.create_tiebreak_round(session, tournament, sorted(group), previous_round_id=round_id)
        session.expire_all()


async def remove_entry(session: AsyncSession, tournament: Tournament, entry_id: int) -> None:
    """Удаляет игрока из тай-брейка совсем: его попытки, слова и участие в раундах, затем саму запись
    участника. Места и (в командном) средние команд пересчитываются без него; продолжения, которые
    без него не нужны, удаляются, недостающие заводятся, раунды, которые теперь можно закрыть, закрываются.
    Необратимо (человек остаётся в списке игроков платформы и его можно подключить заново)."""
    tournament_id = tournament.id
    await session.execute(delete(Attempt).where(Attempt.entry_id == entry_id))
    await session.execute(delete(TiebreakParticipant).where(TiebreakParticipant.entry_id == entry_id))
    await session.execute(delete(DailyWord).where(DailyWord.tournament_id == tournament_id, DailyWord.entry_id == entry_id))
    await session.execute(delete(TournamentEntry).where(TournamentEntry.id == entry_id))
    await session.commit()
    session.expire_all()
    await reconcile_rounds(session, await crud.get_tournament(session, tournament_id))
    await resolve_ready_rounds(session, await crud.get_tournament(session, tournament_id))
