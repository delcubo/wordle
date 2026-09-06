"""
Слой доступа к БД. Роутеры вызывают эти функции, а не пишут SQL/ORM-запросы
напрямую — так вся логика живёт в одном месте.
"""
import secrets
from datetime import date

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import (
    Tournament, TournamentStatus, TournamentEntry, User, DailyWord, DailyWordStatus, Attempt,
    TiebreakRound, TiebreakParticipant, PlayoffMatch, PlayoffGame, AppSettings, ExcludedWord,
)
from api.dictionary import pick_word_for_day, pick_alternative_word, pick_word_for_match
from api.tournament_time import today, day_number_for_date, date_for_day_number


# ---------- Users (глобальная личность) ----------

async def create_user(session: AsyncSession, admin_note: str | None = None, is_test: bool = False) -> User:
    # 8 байт (~11 символов base64url) — короче старых 32-символьных ссылок для
    # удобства, но 64 бита энтропии всё ещё практически не подобрать перебором
    # (см. пункт #17 бэклога: 5 символов, как изначально просили, было бы
    # подобрать перебором реально при отсутствии rate-limit, поэтому выбрана
    # умеренная длина). Уже выданные более длинные токены не трогаем.
    user = User(access_token=secrets.token_urlsafe(8), admin_note=admin_note, is_test=is_test)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def get_test_user_ids(session: AsyncSession) -> set[int]:
    """Игроки, помеченные как личный тестовый аккаунт админа — исключаются из
    подсчёта таблиц результатов (см. standings_view.compute_standings)."""
    result = await session.execute(select(User.id).where(User.is_test.is_(True)))
    return {row[0] for row in result.all()}


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


async def set_user_archived(session: AsyncSession, user_id: int, archived: bool) -> User | None:
    """"Удаление" игрока = перемещение в папку "Удалённые" (см. #12 бэклога).
    При архивации заодно отключает все его текущие активные участия (иначе
    "удалённый" игрок мог бы продолжать играть по своей ссылке) — восстановление
    из архива их обратно не подключает, это отдельное решение админа."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.archived = archived
    session.add(user)
    if archived:
        for entry in await list_entries_for_user(session, user_id):
            entry.active = False
            session.add(entry)
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
    """Только активное участие — отключённый (active=False) игрок для игровых
    эндпоинтов выглядит так, будто он не участвует. Для админских случаев, где
    нужно найти участие независимо от статуса, см. get_entry_including_inactive."""
    result = await session.execute(
        select(TournamentEntry).where(
            TournamentEntry.tournament_id == tournament_id,
            TournamentEntry.user_id == user_id,
            TournamentEntry.active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_entry_including_inactive(session: AsyncSession, tournament_id: int, user_id: int) -> TournamentEntry | None:
    result = await session.execute(
        select(TournamentEntry).where(
            TournamentEntry.tournament_id == tournament_id,
            TournamentEntry.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def set_entry_active(session: AsyncSession, entry_id: int, active: bool) -> TournamentEntry | None:
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        return None
    entry.active = active
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


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
    """Розыгрыши, в которых участвует данный пользователь — для экрана 'мои розыгрыши'.
    Отключённые (active=False) участия не показываются — игрок для них "не подключён"."""
    result = await session.execute(
        select(TournamentEntry).where(TournamentEntry.user_id == user_id, TournamentEntry.active.is_(True))
    )
    return list(result.scalars().all())


async def list_entries_with_tournament_for_user(session: AsyncSession, user_id: int) -> list[tuple[TournamentEntry, Tournament]]:
    """Все участия пользователя (активные и отключённые) вместе с их розыгрышами —
    для отображения в админской вкладке 'Игроки' (см. пункт #13 бэклога)."""
    result = await session.execute(
        select(TournamentEntry, Tournament)
        .join(Tournament, TournamentEntry.tournament_id == Tournament.id)
        .where(TournamentEntry.user_id == user_id)
    )
    return list(result.all())


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

async def get_daily_word_by_id(session: AsyncSession, daily_word_id: int) -> DailyWord | None:
    return await session.get(DailyWord, daily_word_id)


async def get_daily_word_by_day(session: AsyncSession, tournament_id: int, day_number: int) -> DailyWord | None:
    result = await session.execute(
        select(DailyWord).where(
            DailyWord.tournament_id == tournament_id,
            DailyWord.day_number == day_number,
        )
    )
    return result.scalar_one_or_none()


async def _get_used_words(session: AsyncSession, tournament_id: int) -> set[str]:
    """Слова, уже сыгранные в этом розыгрыше, ПЛЮС слова, исключённые админом
    глобально (см. ExcludedWord) — оба множества одинаково не годятся в
    кандидаты для нового слова, так что удобно отдавать их одним набором
    везде, где already_used передаётся в pick_word_for_day/_alternative/_match."""
    result = await session.execute(select(DailyWord.word).where(DailyWord.tournament_id == tournament_id))
    used = {row[0] for row in result.all()}
    return used | await get_excluded_words(session)


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


async def override_attempt(
    session: AsyncSession,
    entry_id: int,
    daily_word_id: int,
    attempts_used: int,
    solved: bool,
    points: int,
    note: str,
) -> Attempt:
    """
    Создаёт или перезаписывает Attempt результатом, заданным админом вручную
    (исправление ошибки или зачёт дня, который участник не мог сыграть) —
    см. api/routers/admin.py::override_day_result. Реальные guesses при этом
    не восстанавливаются, только итог (сколько попыток, угадал ли, очки).
    """
    from datetime import datetime

    attempt = await get_attempt(session, entry_id, daily_word_id)
    if attempt is None:
        attempt = Attempt(entry_id=entry_id, daily_word_id=daily_word_id, guesses=[])
    attempt.attempts_used = attempts_used
    attempt.solved = solved
    attempt.points = points
    attempt.admin_note = note
    if attempt.finished_at is None:
        attempt.finished_at = datetime.utcnow()
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


# ---------- Тай-брейк (championship) ----------

async def _next_free_day_number(session: AsyncSession, tournament_id: int) -> int:
    result = await session.execute(
        select(func.max(DailyWord.day_number)).where(DailyWord.tournament_id == tournament_id)
    )
    return (result.scalar_one_or_none() or 0) + 1


async def create_tiebreak_round(
    session: AsyncSession, tournament: Tournament, entry_ids: list[int], previous_round_id: int | None = None
) -> TiebreakRound:
    """
    Заводит новое слово (продолжает нумерацию дней розыгрыша дальше duration_days,
    так что не конфликтует с обычными днями) и раунд тай-брейка на заданных
    участников. previous_round_id — если это продолжение раунда, часть которого
    осталась равна между собой после предыдущего слова.
    """
    already_used = await _get_used_words(session, tournament.id)
    day_number = await _next_free_day_number(session, tournament.id)
    word = pick_word_for_day(tournament.id, day_number, already_used)

    daily_word = DailyWord(
        tournament_id=tournament.id,
        day_number=day_number,
        word=word,
        calendar_date=today(),
        status=DailyWordStatus.suggested,
    )
    session.add(daily_word)
    await session.flush()

    round_number = 1
    if previous_round_id is not None:
        previous_round = await session.get(TiebreakRound, previous_round_id)
        if previous_round is not None:
            round_number = previous_round.round_number + 1

    tiebreak_round = TiebreakRound(
        tournament_id=tournament.id,
        daily_word_id=daily_word.id,
        round_number=round_number,
        previous_round_id=previous_round_id,
    )
    session.add(tiebreak_round)
    await session.flush()

    for entry_id in entry_ids:
        session.add(TiebreakParticipant(round_id=tiebreak_round.id, entry_id=entry_id))

    await session.commit()
    await session.refresh(tiebreak_round)
    return tiebreak_round


async def list_tiebreak_rounds(session: AsyncSession, tournament_id: int) -> list[TiebreakRound]:
    result = await session.execute(
        select(TiebreakRound)
        .where(TiebreakRound.tournament_id == tournament_id)
        .order_by(TiebreakRound.round_number, TiebreakRound.id)
    )
    return list(result.scalars().all())


async def list_active_tiebreak_rounds(session: AsyncSession, tournament_id: int) -> list[TiebreakRound]:
    result = await session.execute(
        select(TiebreakRound).where(
            TiebreakRound.tournament_id == tournament_id,
            TiebreakRound.completed.is_(False),
        )
    )
    return list(result.scalars().all())


async def list_tiebreak_participants(session: AsyncSession, round_id: int) -> list[TiebreakParticipant]:
    result = await session.execute(
        select(TiebreakParticipant).where(TiebreakParticipant.round_id == round_id)
    )
    return list(result.scalars().all())


async def get_active_tiebreak_round_for_entry(
    session: AsyncSession, tournament_id: int, entry_id: int
) -> TiebreakRound | None:
    """Раунд тай-брейка, в котором участвует entry и который ещё не завершён —
    используется, чтобы отдать этому игроку слово тай-брейка как "слово дня"."""
    result = await session.execute(
        select(TiebreakRound)
        .join(TiebreakParticipant, TiebreakParticipant.round_id == TiebreakRound.id)
        .where(
            TiebreakRound.tournament_id == tournament_id,
            TiebreakRound.completed.is_(False),
            TiebreakParticipant.entry_id == entry_id,
        )
    )
    return result.scalars().first()


async def list_root_tiebreak_rounds(session: AsyncSession, tournament_id: int) -> list[TiebreakRound]:
    """Раунды, с которых началась цепочка тай-брейка (не продолжения) — по одному
    на каждую исходную группу с равными местами."""
    result = await session.execute(
        select(TiebreakRound).where(
            TiebreakRound.tournament_id == tournament_id,
            TiebreakRound.previous_round_id.is_(None),
        )
    )
    return list(result.scalars().all())


async def get_child_rounds(session: AsyncSession, round_id: int) -> list[TiebreakRound]:
    """Раунды-продолжения, заведённые из-за остаточной ничьей внутри round_id."""
    result = await session.execute(
        select(TiebreakRound).where(TiebreakRound.previous_round_id == round_id)
    )
    return list(result.scalars().all())


# ---------- Сетка плей-офф ----------

async def list_playoff_matches(session: AsyncSession, tournament_id: int) -> list[PlayoffMatch]:
    result = await session.execute(
        select(PlayoffMatch)
        .where(PlayoffMatch.tournament_id == tournament_id)
        .order_by(PlayoffMatch.round_number, PlayoffMatch.position)
    )
    return list(result.scalars().all())


async def create_playoff_match(
    session: AsyncSession,
    tournament_id: int,
    round_number: int,
    position: int,
    entry_a_id: int,
    entry_b_id: int,
    scheduled_date: date | None,
) -> PlayoffMatch:
    match = PlayoffMatch(
        tournament_id=tournament_id,
        round_number=round_number,
        position=position,
        entry_a_id=entry_a_id,
        entry_b_id=entry_b_id,
        scheduled_date=scheduled_date,
    )
    session.add(match)
    await session.commit()
    await session.refresh(match)
    return match


async def get_playoff_match_by_position(
    session: AsyncSession, tournament_id: int, round_number: int, position: int
) -> PlayoffMatch | None:
    result = await session.execute(
        select(PlayoffMatch).where(
            PlayoffMatch.tournament_id == tournament_id,
            PlayoffMatch.round_number == round_number,
            PlayoffMatch.position == position,
        )
    )
    return result.scalars().first()


async def list_playoff_matches_for_entry(session: AsyncSession, tournament_id: int, entry_id: int) -> list[PlayoffMatch]:
    """Все пары сетки этого розыгрыша, где участвует entry — обычно активна не
    больше одной одновременно (следующий раунд появляется только после победы)."""
    result = await session.execute(
        select(PlayoffMatch).where(
            PlayoffMatch.tournament_id == tournament_id,
            (PlayoffMatch.entry_a_id == entry_id) | (PlayoffMatch.entry_b_id == entry_id),
        )
    )
    return list(result.scalars().all())


# ---------- Игры внутри пары сетки ----------

async def _get_used_playoff_words(session: AsyncSession, tournament_id: int) -> set[str]:
    result = await session.execute(
        select(PlayoffGame.word)
        .join(PlayoffMatch, PlayoffGame.match_id == PlayoffMatch.id)
        .where(PlayoffMatch.tournament_id == tournament_id)
    )
    return {row[0] for row in result.all()}


async def get_all_used_words(session: AsyncSession, tournament_id: int) -> set[str]:
    """Все слова, уже использованные в розыгрыше — обычные дни, тай-брейк
    (тоже DailyWord) и игры сетки — чтобы новое слово нигде не повторялось."""
    return await _get_used_words(session, tournament_id) | await _get_used_playoff_words(session, tournament_id)


async def list_playoff_games(session: AsyncSession, match_id: int) -> list[PlayoffGame]:
    result = await session.execute(
        select(PlayoffGame).where(PlayoffGame.match_id == match_id).order_by(PlayoffGame.game_number)
    )
    return list(result.scalars().all())


async def create_playoff_game(
    session: AsyncSession,
    tournament_id: int,
    match_id: int,
    game_number: int,
    calendar_date: date,
    is_sudden_death: bool = False,
) -> PlayoffGame:
    already_used = await get_all_used_words(session, tournament_id)
    word = pick_word_for_match(match_id, game_number, already_used)
    game = PlayoffGame(
        match_id=match_id,
        game_number=game_number,
        word=word,
        calendar_date=calendar_date,
        is_sudden_death=is_sudden_death,
        entry_a_guesses=[],
        entry_b_guesses=[],
    )
    session.add(game)
    await session.commit()
    await session.refresh(game)
    return game


# ---------- Общие настройки сайта ----------

async def get_app_settings(session: AsyncSession) -> AppSettings:
    """Единственная строка настроек (id=1) — заводится лениво при первом обращении."""
    settings = await session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1, theme="dark")
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


async def set_theme(session: AsyncSession, theme: str) -> AppSettings:
    settings = await get_app_settings(session)
    settings.theme = theme
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    return settings


# ---------- Словарь: слова, исключённые админом вручную ----------

async def get_excluded_words(session: AsyncSession) -> set[str]:
    result = await session.execute(select(ExcludedWord.word))
    return {row[0] for row in result.all()}


async def list_excluded_words(session: AsyncSession) -> list[ExcludedWord]:
    result = await session.execute(select(ExcludedWord).order_by(ExcludedWord.excluded_at.desc()))
    return list(result.scalars().all())


async def exclude_word(session: AsyncSession, word: str) -> ExcludedWord:
    result = await session.execute(select(ExcludedWord).where(ExcludedWord.word == word))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    excluded = ExcludedWord(word=word)
    session.add(excluded)
    await session.commit()
    await session.refresh(excluded)
    return excluded


async def unexclude_word(session: AsyncSession, excluded_id: int) -> bool:
    excluded = await session.get(ExcludedWord, excluded_id)
    if excluded is None:
        return False
    await session.delete(excluded)
    await session.commit()
    return True


async def save_playoff_guess(
    session: AsyncSession,
    game: PlayoffGame,
    side: str,
    guess: str,
    solved: bool,
    finished: bool,
) -> PlayoffGame:
    """side — 'a' или 'b', какая сторона пары делает ход."""
    guesses_field = f"entry_{side}_guesses"
    guesses = [*getattr(game, guesses_field), guess]
    setattr(game, guesses_field, guesses)
    if finished:
        setattr(game, f"entry_{side}_attempts_used", len(guesses))
        setattr(game, f"entry_{side}_solved", solved)
    session.add(game)
    await session.commit()
    await session.refresh(game)
    return game
