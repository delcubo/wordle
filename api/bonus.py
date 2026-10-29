"""
Бонусные слова Стандартного режима и основного этапа Чемпионата.

Дни розыгрыша делятся на блоки по N дней (Tournament.bonus_every_days): 1..N, N+1..2N и т.д.;
бонусных слов столько, сколько полных блоков (длительность // N). Бонус k открывается игроку,
если в k-м блоке у него нет пропущенных дней (пропуск — как в таблице: день без завершённой
попытки; дни до подключения тоже пропуски). Блоки независимы. Бонус открывается сразу после
завершения слова последнего дня блока (дня k·N) и играется ТОЛЬКО в этот день — до конца дня.
Очки — по шкале розыгрыша (scoring_rules); не угадал — 0, штрафа за отказ нет.

Бонусное слово хранится как DailyWord с пометкой bonus_number и «служебным» номером дня
BONUS_DAY_BASE + k (вне диапазона настоящих дней — так оно не пересекается с обычными словами
дней и не попадает в таблицы по дням); calendar_date — день открытия.

Состояния бонуса k для игрока (compute_states):
  played   — бонус сыгран (есть очки, возможно 0);
  open     — доступен прямо сейчас (день открытия, слово дня завершено, бонус ещё не сыгран);
  pending  — день открытия сегодня, слово дня ещё не завершено (откроется после него);
  upcoming — день открытия ещё впереди, пропусков в блоке пока нет;
  lost     — в блоке был пропуск, бонус потерян;
  expired  — право было, но день открытия прошёл, а бонус не сыгран (или не доигран).
"""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentType, TournamentEntry, DailyWord, DailyWordStatus, Attempt
from api.dictionary import pick_word_for_label, pick_alternative_word, SUPPORTED_LENGTHS
from api.tournament_time import today, day_number_for_date
from api import crud

BONUS_DAY_BASE = 1000
MAX_BONUS_LENGTH_DEFAULT = 6


def supports_bonus(tournament: Tournament) -> bool:
    """Бонусы бывают у розыгрышей с днями и очками: Стандартный и основной этап Чемпионата."""
    return tournament.type in (TournamentType.standard, TournamentType.championship) and tournament.duration_days is not None


def bonus_slots(tournament: Tournament) -> int:
    """Сколько бонусных слов в розыгрыше (0, если опция выключена или N не задано)."""
    if not tournament.bonus_enabled or not tournament.bonus_every_days or not tournament.duration_days:
        return 0
    return tournament.duration_days // tournament.bonus_every_days


def opening_day(tournament: Tournament, number: int) -> int:
    """Номер дня, в который открывается бонус number (последний день его блока)."""
    return number * tournament.bonus_every_days


def active_for_players(tournament: Tournament) -> bool:
    """Бонусы показываются игрокам, пока идёт основной этап (не плей-офф и не тай-брейк чемпионата)."""
    from api.models import TournamentStatus
    return bonus_slots(tournament) > 0 and tournament.status not in (TournamentStatus.tiebreak, TournamentStatus.playoff)


async def list_bonus_words(session: AsyncSession, tournament_id: int) -> list[DailyWord]:
    result = await session.execute(
        select(DailyWord)
        .where(DailyWord.tournament_id == tournament_id, DailyWord.bonus_number.is_not(None))
        .order_by(DailyWord.bonus_number)
    )
    return list(result.scalars().all())


async def get_bonus_word(session: AsyncSession, tournament_id: int, number: int) -> DailyWord | None:
    result = await session.execute(
        select(DailyWord).where(DailyWord.tournament_id == tournament_id, DailyWord.bonus_number == number)
    )
    return result.scalar_one_or_none()


async def bonus_word_has_attempts(session: AsyncSession, daily_word_id: int) -> bool:
    return await crud.daily_word_has_attempts(session, daily_word_id)


async def any_bonus_attempts(session: AsyncSession, tournament_id: int) -> bool:
    for dw in await list_bonus_words(session, tournament_id):
        if await crud.daily_word_has_attempts(session, dw.id):
            return True
    return False


def _calendar_date(tournament: Tournament, number: int):
    return tournament.start_date + timedelta(days=opening_day(tournament, number) - 1)


async def sync_words(session: AsyncSession, tournament: Tournament) -> None:
    """Приводит бонусные слова в соответствие с настройками: недостающие создаются (по длине
    по умолчанию, слово подбирается по сиду и не повторяет ничего в розыгрыше), лишние (после
    уменьшения числа блоков или выключения опции) удаляются, если их ещё никто не начал, иначе —
    ValueError. У ещё не начатых слов обновляется день открытия (при смене N)."""
    slots = bonus_slots(tournament)
    existing = {dw.bonus_number: dw for dw in await list_bonus_words(session, tournament.id)}
    for number, dw in sorted(existing.items()):
        if number > slots:
            if await crud.daily_word_has_attempts(session, dw.id):
                raise ValueError(f"Бонусное слово {number} уже начали отгадывать — убрать его нельзя")
            await session.execute(delete(DailyWord).where(DailyWord.id == dw.id))
    await session.commit()
    if slots == 0:
        return
    used = await crud._get_used_words(session, tournament.id)
    length = tournament.bonus_default_length or MAX_BONUS_LENGTH_DEFAULT
    for number in range(1, slots + 1):
        dw = existing.get(number)
        if dw is None:
            word = pick_word_for_label(f"bonus:{tournament.id}:{number}", used, length)
            used.add(word)
            session.add(DailyWord(
                tournament_id=tournament.id, day_number=BONUS_DAY_BASE + number, bonus_number=number, word=word,
                calendar_date=_calendar_date(tournament, number), status=DailyWordStatus.suggested,
            ))
        elif dw.calendar_date != _calendar_date(tournament, number):
            if await crud.daily_word_has_attempts(session, dw.id):
                raise ValueError("Бонусные слова уже начаты — менять N поздно")
            dw.calendar_date = _calendar_date(tournament, number)
            session.add(dw)
    await session.commit()


async def set_word(session: AsyncSession, tournament: Tournament, number: int, word: str) -> DailyWord:
    dw = await get_bonus_word(session, tournament.id, number)
    if dw is None:
        raise ValueError("Бонусного слова с таким номером нет")
    if await crud.daily_word_has_attempts(session, dw.id):
        raise ValueError("Это бонусное слово уже начали отгадывать — менять поздно")
    dw.word = word
    dw.status = DailyWordStatus.confirmed
    session.add(dw)
    await session.commit()
    await session.refresh(dw)
    return dw


async def reroll_word(session: AsyncSession, tournament: Tournament, number: int, length: int | None = None) -> DailyWord:
    """«Предложить другое» (длина сохраняется) или смена длины слова: подбирается новое слово."""
    dw = await get_bonus_word(session, tournament.id, number)
    if dw is None:
        raise ValueError("Бонусного слова с таким номером нет")
    if await crud.daily_word_has_attempts(session, dw.id):
        raise ValueError("Это бонусное слово уже начали отгадывать — менять поздно")
    used = await crud.get_all_used_words(session, tournament.id)
    dw.word = pick_alternative_word(used, exclude=dw.word, length=length or len(dw.word))
    dw.status = DailyWordStatus.suggested
    session.add(dw)
    await session.commit()
    await session.refresh(dw)
    return dw


def attempt_finished(attempt: Attempt | None) -> bool:
    return attempt is not None and (attempt.solved or attempt.attempts_used >= 6)


async def compute_states(
    session: AsyncSession, tournament: Tournament, entries: list[TournamentEntry]
) -> dict[int, list[dict]]:
    """Состояния всех бонусов для перечисленных участников: {entry_id: [{number, state, ...}]}."""
    slots = bonus_slots(tournament)
    if not slots or not entries:
        return {}
    daily = {dw.id: dw for dw in await crud.list_daily_words(session, tournament.id)}
    bonus_words = {dw.bonus_number: dw for dw in await list_bonus_words(session, tournament.id)}
    bonus_number_by_word = {dw.id: number for number, dw in bonus_words.items()}
    ids = [e.id for e in entries]
    result = await session.execute(select(Attempt).where(Attempt.entry_id.in_(ids)))
    finished_days: dict[int, set[int]] = {eid: set() for eid in ids}
    bonus_attempts: dict[int, dict[int, Attempt]] = {eid: {} for eid in ids}
    for a in result.scalars().all():
        if a.daily_word_id in bonus_number_by_word:
            bonus_attempts[a.entry_id][bonus_number_by_word[a.daily_word_id]] = a
        elif a.daily_word_id in daily and attempt_finished(a):
            finished_days[a.entry_id].add(daily[a.daily_word_id].day_number)

    every = tournament.bonus_every_days
    current_day = day_number_for_date(tournament.start_date, today())
    states: dict[int, list[dict]] = {}
    for entry in entries:
        rows = []
        for number in range(1, slots + 1):
            block_start, end = (number - 1) * every + 1, number * every
            dw = bonus_words.get(number)
            att = bonus_attempts[entry.id].get(number)
            lost = any(d < current_day and d not in finished_days[entry.id] for d in range(block_start, end + 1))
            if attempt_finished(att):
                state = "played"
            elif lost:
                state = "lost"
            elif current_day < end:
                state = "upcoming"
            elif current_day == end:
                state = "open" if end in finished_days[entry.id] else "pending"
            else:
                state = "expired"
            rows.append({
                "number": number, "opening_day": end, "block_start": block_start, "state": state,
                "length": len(dw.word) if dw else tournament.bonus_default_length,
                "word_id": dw.id if dw else None,
                "points": att.points if state == "played" else None,
                "attempts_used": att.attempts_used if att else 0,
                "solved": bool(att.solved) if att else False,
                "guesses": list(att.guesses) if att else [],
            })
        states[entry.id] = rows
    return states
