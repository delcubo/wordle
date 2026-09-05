"""
Слой доступа к БД. Роутеры вызывают эти функции, а не пишут SQL/ORM-запросы
напрямую — так вся логика живёт в одном месте.
"""
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import (
    Tournament, TournamentStatus, TournamentEntry, User, DailyWord, DailyWordStatus, Attempt,
)
from api.dictionary import pick_word_for_day, pick_alternative_word
from api.tournament_time import today, day_number_for_date, date_for_day_number


# ---------- Users (глобальная личность) ----------

async def create_user(session: AsyncSession, admin_note: str | None = None) -> User:
    user = User(access_token=secrets.token_urlsafe(24), admin_note=admin_note)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def get_user_by_token(session: AsyncSession, access_token: str) -> User | None:
    result = await session.execute(select(User).where(User.access_token == access_token))
    return result.scalar_one_or_none()


async def edit_user_note(session: AsyncSession, user_id: int, admin_note: str | None) -> User | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.admin_note = admin_note
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


# ---------- Tournaments ----------

async def get_tournament(session: AsyncSession, tournament_id: int) -> Tournament | None:
    return await session.get(Tournament, tournament_id)


async def list_tournaments(session: AsyncSession) -> list[Tournament]:
    result = await session.execute(select(Tournament).order_by(Tournament.created_at.desc()))
    return list(result.scalars().all())


async def list_active_tournaments(session: AsyncSession) -> list[Tournament]:
    result = await session.execute(select(Tournament).where(Tournament.status == TournamentStatus.active))
    return list(result.scalars().all())


async def get_other_active_tournament_of_type(
    session: AsyncSession, tournament_type, exclude_id: int
) -> Tournament | None:
    """Ищет уже активный розыгрыш того же типа, кроме самого exclude_id — используется,
    чтобы не дать активировать вторую бессрочную игру, пока идёт текущая."""
    result = await session.execute(
        select(Tournament).where(
            Tournament.type == tournament_type,
            Tournament.status == TournamentStatus.active,
            Tournament.id != exclude_id,
        )
    )
    return result.scalars().first()


# ---------- Tournament entries (участие User в Tournament) ----------

async def callsign_taken(session: AsyncSession, tournament_id: int, callsign: str) -> bool:
    result = await session.execute(
        select(TournamentEntry).where(
            TournamentEntry.tournament_id == tournament_id,
            TournamentEntry.callsign == callsign,
        )
    )
    return result.scalar_one_or_none() is not None


async def get_entry(session: AsyncSession, tournament_id: int, user_id: int) -> TournamentEntry | None:
    result = await session.execute(
        select(TournamentEntry).where(
            TournamentEntry.tournament_id == tournament_id,
            TournamentEntry.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_entry(
    session: AsyncSession, tournament: Tournament, user_id: int, callsign: str
) -> TournamentEntry:
    current_day = day_number_for_date(tournament.start_date, today())
    entry = TournamentEntry(
        tournament_id=tournament.id,
        user_id=user_id,
        callsign=callsign,
        joined_on_day=max(current_day, 1),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def list_entries(session: AsyncSession, tournament_id: int) -> list[TournamentEntry]:
    result = await session.execute(
        select(TournamentEntry).where(TournamentEntry.tournament_id == tournament_id).order_by(TournamentEntry.joined_at)
    )
    return list(result.scalars().all())


async def list_entries_for_user(session: AsyncSession, user_id: int) -> list[TournamentEntry]:
    """Розыгрыши, в которых участвует данный пользователь — для экрана 'мои розыгрыши'."""
    result = await session.execute(
        select(TournamentEntry).where(TournamentEntry.user_id == user_id)
    )
    return list(result.scalars().all())


async def edit_entry_callsign(session: AsyncSession, entry_id: int, callsign: str) -> TournamentEntry | None:
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        return None
    entry.callsign = callsign
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


# ---------- Daily words (с подтверждением админом) ----------

async def get_daily_word_by_day(session: AsyncSession, tournament_id: int, day_number: int) -> DailyWord | None:
    result = await session.execute(
        select(DailyWord).where(
            DailyWord.tournament_id == tournament_id,
            DailyWord.day_number == day_number,
        )
    )
    return result.scalar_one_or_none()


async def _get_used_words(session: AsyncSession, tournament_id: int) -> set[str]:
    result = await session.execute(select(DailyWord.word).where(DailyWord.tournament_id == tournament_id))
    return {row[0] for row in result.all()}


async def get_or_suggest_daily_word(session: AsyncSession, tournament: Tournament, day_number: int) -> DailyWord:
    """
    Возвращает DailyWord на день, создавая его как 'suggested' при первом обращении
    (используется и когда админ открывает вкладку подтверждения слова заранее, и
    когда день уже наступил, а слово ещё ни разу не запрашивалось — тогда оно
    сразу считается действующим, см. save_guess/get_or_create_attempt, которые
    используют слово независимо от статуса).
    """
    existing = await get_daily_word_by_day(session, tournament.id, day_number)
    if existing:
        return existing

    already_used = await _get_used_words(session, tournament.id)
    word = pick_word_for_day(tournament.id, day_number, already_used)
    daily_word = DailyWord(
        tournament_id=tournament.id,
        day_number=day_number,
        word=word,
        calendar_date=date_for_day_number(tournament.start_date, day_number),
        status=DailyWordStatus.suggested,
    )
    session.add(daily_word)
    await session.commit()
    await session.refresh(daily_word)
    return daily_word


async def confirm_daily_word(
    session: AsyncSession, daily_word: DailyWord, override_word: str | None
) -> DailyWord:
    """
    Подтверждает слово (override_word=None — соглашаемся с предложенным) или
    заменяет его вручную (override_word задан; вызывающий код уже должен был
    провалидировать его через dictionary.validate_manual_word).
    """
    if override_word:
        daily_word.word = override_word
    daily_word.status = DailyWordStatus.confirmed
    session.add(daily_word)
    await session.commit()
    await session.refresh(daily_word)
    return daily_word


async def reroll_daily_word(session: AsyncSession, daily_word: DailyWord) -> DailyWord:
    """
    Заменяет предложенное слово на другое случайное (кнопка "предложить другое
    слово"). Статус остаётся suggested — админ по-прежнему может согласиться,
    заменить вручную или запросить ещё вариант.
    """
    already_used = await _get_used_words(session, daily_word.tournament_id)
    daily_word.word = pick_alternative_word(already_used, exclude=daily_word.word)
    session.add(daily_word)
    await session.commit()
    await session.refresh(daily_word)
    return daily_word


async def list_daily_words(session: AsyncSession, tournament_id: int) -> list[DailyWord]:
    result = await session.execute(
        select(DailyWord).where(DailyWord.tournament_id == tournament_id).order_by(DailyWord.day_number)
    )
    return list(result.scalars().all())


# ---------- Attempts ----------

async def get_attempt(session: AsyncSession, entry_id: int, daily_word_id: int) -> Attempt | None:
    result = await session.execute(
        select(Attempt).where(
            Attempt.entry_id == entry_id,
            Attempt.daily_word_id == daily_word_id,
        )
    )
    return result.scalar_one_or_none()


async def get_or_create_attempt(session: AsyncSession, entry_id: int, daily_word_id: int) -> Attempt:
    attempt = await get_attempt(session, entry_id, daily_word_id)
    if attempt:
        return attempt
    attempt = Attempt(
        entry_id=entry_id,
        daily_word_id=daily_word_id,
        guesses=[],
        attempts_used=0,
        solved=False,
        points=0,
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt


async def list_attempts_for_tournament(session: AsyncSession, tournament_id: int) -> list[Attempt]:
    result = await session.execute(
        select(Attempt)
        .join(DailyWord, Attempt.daily_word_id == DailyWord.id)
        .where(DailyWord.tournament_id == tournament_id)
    )
    return list(result.scalars().all())


async def save_guess(
    session: AsyncSession,
    attempt: Attempt,
    guess: str,
    solved: bool,
    finished: bool,
    points: int | None,
) -> Attempt:
    attempt.guesses = [*attempt.guesses, guess]
    attempt.attempts_used = len(attempt.guesses)
    attempt.solved = solved
    if finished:
        from datetime import datetime
        attempt.finished_at = datetime.utcnow()
        attempt.points = points or 0
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt
