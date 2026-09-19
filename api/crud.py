"""
Слой доступа к БД. Роутеры вызывают эти функции, а не пишут SQL/ORM-запросы
напрямую — так вся логика живёт в одном месте.
"""
import secrets
from datetime import date

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import (
    Tournament, TournamentStatus, TournamentType, TournamentEntry, User, DailyWord, DailyWordStatus, Attempt,
    TiebreakRound, TiebreakParticipant, PlayoffMatch, PlayoffGame, AppSettings, ExcludedWord, AddedWord,
)
from api.dictionary import pick_word_for_day, pick_alternative_word, pick_word_for_match
from api.tournament_time import today, day_number_for_date, date_for_day_number


# ---------- Users (глобальная личность) ----------

async def create_user(session: AsyncSession, admin_note: str | None = None) -> User:
    # 8 байт (~11 символов base64url) — короче старых 32-символьных ссылок для
    # удобства, но 64 бита энтропии всё ещё практически не подобрать перебором
    # (см. пункт #17 бэклога: 5 символов, как изначально просили, было бы
    # подобрать перебором реально при отсутствии rate-limit, поэтому выбрана
    # умеренная длина). Уже выданные более длинные токены не трогаем.
    user = User(access_token=secrets.token_urlsafe(8), admin_note=admin_note)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def admin_note_taken(session: AsyncSession, admin_note: str, exclude_user_id: int | None = None) -> bool:
    """Проверка на дубль заметки игрока (см. пункт бэклога) — сравнение без
    учёта регистра, чтобы 'Вася' и 'вася' тоже считались одним и тем же."""
    result = await session.execute(select(User).where(func.lower(User.admin_note) == admin_note.lower()))
    users = result.scalars().all()
    return any(u.id != exclude_user_id for u in users)


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


async def disconnect_user_from_all(session: AsyncSession, user_id: int) -> User | None:
    """Отключить игрока от всех розыгрышей, в которых он сейчас активен, без
    архивации — личная ссылка продолжает работать, игрок просто нигде не
    участвует, пока админ не подключит его обратно (см. пункт бэклога про
    разделение 'Отключить' и 'В архив')."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    for entry in await list_entries_for_user(session, user_id):
        entry.active = False
        session.add(entry)
    await session.commit()
    return user


async def regenerate_access_token(session: AsyncSession, user_id: int) -> User | None:
    """Выдаёт новую персональную ссылку взамен утерянной старой — доступ тот
    же (тот же User, те же участия), старый токен просто перестаёт работать."""
    user = await session.get(User, user_id)
    if user is None:
        return None
    user.access_token = secrets.token_urlsafe(8)
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


async def set_tournament_paused(session: AsyncSession, tournament_id: int, paused: bool) -> Tournament | None:
    """Немедленно приостанавливает/возобновляет розыгрыш для всех участников
    без изменения его фазы (см. пункт бэклога) — см. Tournament.paused."""
    tournament = await get_tournament(session, tournament_id)
    if tournament is None:
        return None
    tournament.paused = paused
    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    return tournament


async def set_tournament_archived(session: AsyncSession, tournament_id: int, archived: bool) -> Tournament | None:
    """Ручное перемещение розыгрыша в архив (или обратно) — см. пункт бэклога:
    админ сам решает, когда убрать приостановленный/завершённый розыгрыш."""
    tournament = await get_tournament(session, tournament_id)
    if tournament is None:
        return None
    tournament.archived = archived
    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    return tournament


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


async def disconnect_all_entries(session: AsyncSession, tournament_id: int) -> int:
    """Отключить одной кнопкой сразу всех активных участников розыгрыша (без
    удаления записей и статистики — как обычное отключение по одному, см.
    set_entry_active). Возвращает число реально отключённых участий."""
    count = 0
    for entry in await list_entries(session, tournament_id):
        if entry.active:
            entry.active = False
            session.add(entry)
            count += 1
    await session.commit()
    return count


async def _pick_default_callsign(session: AsyncSession, tournament_id: int, user: User) -> str:
    """Позывной по умолчанию для массового подключения (см. add_all_users) —
    заметка админа, если она есть и ещё не занята в этом розыгрыше, иначе
    гарантированно уникальный вариант по id игрока. Админ может переименовать
    его позже как обычно (см. edit_entry_callsign)."""
    note = (user.admin_note or "").strip()
    if note and not await callsign_taken(session, tournament_id, note):
        return note
    candidate = f"#игрок{user.id}"
    suffix = 1
    while await callsign_taken(session, tournament_id, candidate):
        suffix += 1
        candidate = f"#игрок{user.id}-{suffix}"
    return candidate


async def add_all_users(session: AsyncSession, tournament: Tournament) -> int:
    """
    Быстро подключает к розыгрышу сразу всех зарегистрированных на платформе
    (неудалённых) игроков — чтобы не добавлять по одному вручную. Уже
    подключённых пропускает; тех, кого раньше отключили от ЭТОГО розыгрыша,
    просто подключает обратно (сохраняя прежний позывной и историю попыток —
    как при подключении по одному, см. api/routers/admin.py::add_entry).
    Новым (никогда не участвовавшим в этом розыгрыше) подбирает позывной по
    умолчанию (см. _pick_default_callsign).

    Возвращает число реально подключённых (новых + переподключённых) участников.
    """
    count = 0
    for user in await list_users(session):
        if user.archived:
            continue
        existing = await get_entry_including_inactive(session, tournament.id, user.id)
        if existing is not None:
            if existing.active:
                continue
            await set_entry_active(session, existing.id, True)
            count += 1
            continue
        callsign = await _pick_default_callsign(session, tournament.id, user)
        await create_entry(session, tournament, user.id, callsign)
        count += 1
    return count


async def transfer_entries(
    session: AsyncSession, from_tournament: Tournament, to_tournament: Tournament, entry_ids: list[int]
) -> list[dict]:
    """
    Массовый переброс выбранных участий из from_tournament в to_tournament —
    см. пункт бэклога про переброску игроков. Каждый entry_id обрабатывается
    независимо (best-effort): позывной переносится, если свободен в целевом
    розыгрыше, иначе этот игрок пропускается (ничего не меняется ни в одном
    из двух розыгрышей) с причиной в результате, остальные переносятся как
    обычно. Три случая по игроку в целевом розыгрыше:
      - не участвовал — создаётся новая запись с перенесённым позывным;
      - есть неактивная запись — реактивируется, позывной перезаписывается
        перенесённым (с проверкой на занятость);
      - уже активен там — запись не трогается (позывной остаётся прежним),
        только отключается в исходном розыгрыше.
    В исходном розыгрыше участие отключается (active=False), история и очки
    не удаляются — как при обычном ручном отключении.
    """
    results = []
    for entry_id in entry_ids:
        entry = await session.get(TournamentEntry, entry_id)
        if entry is None or entry.tournament_id != from_tournament.id:
            results.append({"entry_id": entry_id, "callsign": "", "ok": False, "message": "Участие не найдено"})
            continue

        callsign = entry.callsign
        existing = await get_entry_including_inactive(session, to_tournament.id, entry.user_id)

        if existing is not None and existing.active:
            await set_entry_active(session, entry.id, False)
            results.append({
                "entry_id": entry.id, "callsign": existing.callsign, "ok": True,
                "message": "Уже участвовал в целевом розыгрыше — позывной там не изменён",
            })
            continue

        if existing is not None:
            if callsign != existing.callsign and await callsign_taken(session, to_tournament.id, callsign):
                results.append({
                    "entry_id": entry.id, "callsign": callsign, "ok": False,
                    "message": f"Позывной «{callsign}» уже занят в «{to_tournament.title}»",
                })
                continue
            await edit_entry_callsign(session, existing.id, callsign)
            await set_entry_hidden(session, existing.id, entry.hidden_from_standings)
            await set_entry_active(session, existing.id, True)
            await set_entry_active(session, entry.id, False)
            results.append({"entry_id": entry.id, "callsign": callsign, "ok": True, "message": None})
            continue

        if await callsign_taken(session, to_tournament.id, callsign):
            results.append({
                "entry_id": entry.id, "callsign": callsign, "ok": False,
                "message": f"Позывной «{callsign}» уже занят в «{to_tournament.title}»",
            })
            continue
        await create_entry(session, to_tournament, entry.user_id, callsign, entry.hidden_from_standings)
        await set_entry_active(session, entry.id, False)
        results.append({"entry_id": entry.id, "callsign": callsign, "ok": True, "message": None})

    return results


async def set_entry_active(session: AsyncSession, entry_id: int, active: bool) -> TournamentEntry | None:
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        return None
    entry.active = active
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def set_entry_hidden(session: AsyncSession, entry_id: int, hidden: bool) -> TournamentEntry | None:
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        return None
    entry.hidden_from_standings = hidden
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def create_entry(
    session: AsyncSession, tournament: Tournament, user_id: int, callsign: str, hidden_from_standings: bool = False
) -> TournamentEntry:
    current_day = day_number_for_date(tournament.start_date, today())
    entry = TournamentEntry(
        tournament_id=tournament.id,
        user_id=user_id,
        callsign=callsign,
        joined_on_day=max(current_day, 1),
        hidden_from_standings=hidden_from_standings,
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


async def get_entries_played_today(session: AsyncSession, tournament: Tournament) -> dict[int, dict]:
    """entry_id -> {attempts_used, started_at, finished_at} участников, уже
    завершивших сегодняшнее слово (в том же смысле, что already_played на
    игровой странице — угадал либо исчерпал все 6 попыток) — для колонки
    статуса в бессрочном режиме, включая время начала и продолжительность
    игры (см. пункт бэклога). Пустой словарь, если сегодня ещё нет слова дня
    (розыгрыш не начался/на паузе) — вызывающий код в этом случае просто не
    подсветит никого. Для standard тот же смысл (слово текущего дня в
    пределах duration_days); для knockout — см. get_knockout_today_status."""
    if tournament.type == TournamentType.knockout:
        return (await get_knockout_today_status(session, tournament))[0]
    day_number = day_number_for_date(tournament.start_date, today())
    if day_number < 1:
        return {}
    if tournament.duration_days is not None and day_number > tournament.duration_days:
        return {}
    daily_word = await get_daily_word_by_day(session, tournament.id, day_number)
    if daily_word is None:
        return {}
    result = await session.execute(
        select(Attempt.entry_id, Attempt.attempts_used, Attempt.started_at, Attempt.finished_at).where(
            Attempt.daily_word_id == daily_word.id,
            (Attempt.solved.is_(True)) | (Attempt.attempts_used >= 6),
        )
    )
    return {
        entry_id: {"attempts_used": attempts_used, "started_at": started_at, "finished_at": finished_at}
        for entry_id, attempts_used, started_at, finished_at in result.all()
    }


async def get_knockout_today_status(
    session: AsyncSession, tournament: Tournament
) -> tuple[dict[int, dict], set[int]]:
    """
    Для розыгрыша на вылет: (уже сыгравшие, все у кого сегодня есть игра).
    Игра пары считается сегодняшней, если её calendar_date — сегодня; если
    их несколько (sudden death в тот же день), берётся последняя. Первый
    элемент — entry_id -> {attempts_used, started_at, finished_at} для тех,
    кто эту игру уже завершил (started_at/finished_at могут быть None у игр,
    сыгранных до появления этих колонок); второй — участники, у которых
    сегодня вообще есть игра (нужно, чтобы не подсвечивать "ещё не играл"
    тех, кто сегодня не играет — выбыл или ждёт следующий раунд).
    """
    played: dict[int, dict] = {}
    has_game: set[int] = set()
    today_date = today()
    for match in await list_playoff_matches(session, tournament.id):
        games = [g for g in await list_playoff_games(session, match.id) if g.calendar_date == today_date]
        if not games:
            continue
        game = games[-1]
        for side, entry_id in (("a", match.entry_a_id), ("b", match.entry_b_id)):
            if entry_id is None:
                continue
            has_game.add(entry_id)
            attempts_used = getattr(game, f"entry_{side}_attempts_used")
            if attempts_used is not None:
                played[entry_id] = {
                    "attempts_used": attempts_used,
                    "started_at": getattr(game, f"entry_{side}_started_at"),
                    "finished_at": getattr(game, f"entry_{side}_finished_at"),
                }
    return played, has_game


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

async def reset_todays_attempt(session: AsyncSession, entry: TournamentEntry, tournament: Tournament) -> bool:
    """
    Сбрасывает попытку участника за сегодняшний день розыгрыша — удаляет
    Attempt целиком, чтобы для игрока это выглядело так, будто он ещё не
    играл сегодня (get_or_create_attempt на следующей отправке заведёт новую
    попытку с нуля). Не про исправление результата (см. override_day_result в
    api/routers/admin.py) — про полный повторный шанс на сегодня.

    Не применимо к knockout (там нет слова дня вне сетки) и к tiebreak (там
    номер дня раундовый, а не календарный — см. api/routers/game.py::_resolve_context)
    и к дням вне диапазона розыгрыша. Возвращает True, только если реально
    было что сбрасывать.
    """
    if tournament.type in (TournamentType.knockout, TournamentType.tiebreak):
        return False
    day_number = day_number_for_date(tournament.start_date, today())
    if day_number < 1:
        return False
    if tournament.duration_days is not None and day_number > tournament.duration_days:
        return False
    daily_word = await get_daily_word_by_day(session, tournament.id, day_number)
    if daily_word is None:
        return False
    attempt = await get_attempt(session, entry.id, daily_word.id)
    if attempt is None:
        return False
    await session.delete(attempt)
    await session.commit()
    return True


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


async def _get_attempt_for_update(session: AsyncSession, entry_id: int, daily_word_id: int) -> Attempt | None:
    """Как get_attempt, но блокирует найденную строку (SELECT ... FOR UPDATE)
    до конца транзакции — см. get_or_create_attempt."""
    result = await session.execute(
        select(Attempt)
        .where(Attempt.entry_id == entry_id, Attempt.daily_word_id == daily_word_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def get_or_create_attempt(session: AsyncSession, entry_id: int, daily_word_id: int) -> Attempt:
    """
    Используется на пути отправки попытки (см. api/routers/game.py::submit_guess),
    поэтому блокирует строку на время транзакции: без этого два почти
    одновременных запроса с одним и тем же словом (например, повторная
    отправка из-за сетевой задержки — см. пункт бэклога) читали одинаковый
    guesses[] ДО того, как другой закоммитит свой, и один из результатов
    просто терялся (потерянное обновление). С блокировкой второй запрос ждёт,
    пока первый зафиксируется, и продолжает уже от актуального состояния.

    Для самой первой попытки дня, когда строки ещё нет, блокировать нечего —
    от одновременного создания дубликата защищает уникальный индекс
    (entry_id, daily_word_id): если оба запроса всё же успели одновременно
    дойти до вставки, проигравший ловит IntegrityError и просто перечитывает
    (тоже с блокировкой) то, что успел зафиксировать выигравший.
    """
    attempt = await _get_attempt_for_update(session, entry_id, daily_word_id)
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
    try:
        # flush, а не commit: вставленная строка остаётся внутри транзакции и
        # держит блокировку до save_guess — иначе между созданием и сохранением
        # первой попытки был бы промежуток без замка, и параллельные запросы
        # могли бы получить подсказки, не записав попытки (см. пункт про гонки
        # в разборе безопасности). Второй запрос упрётся в уникальный индекс,
        # дождётся коммита первого и перечитает уже сохранённое.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        attempt = await _get_attempt_for_update(session, entry_id, daily_word_id)
        if attempt is None:
            raise
        return attempt
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


async def compute_played_streak(session: AsyncSession, tournament_id: int, entry_id: int, through_day: int) -> int:
    """
    Число подряд идущих сыгранных дней розыгрыша, считая назад от through_day
    включительно — для строки "дней подряд без пропуска" в копируемом отчёте
    (см. пункт бэклога). День считается сыгранным по тому же правилу, что и
    флаг пропуска в таблице результатов (см. standings_view.compute_standings):
    попытка завершена (угадано либо исчерпаны все 6 попыток). Дни до
    подключения участника автоматически обрывают серию тем же образом, что и
    обычный пропуск — отдельной проверки на joined_on_day не нужно.
    """
    result = await session.execute(
        select(DailyWord.day_number, Attempt.solved, Attempt.attempts_used)
        .join(Attempt, Attempt.daily_word_id == DailyWord.id)
        .where(DailyWord.tournament_id == tournament_id, Attempt.entry_id == entry_id)
    )
    finished_days = {
        day_number for day_number, solved, attempts_used in result.all()
        if solved or attempts_used >= 6
    }
    streak = 0
    day = through_day
    while day in finished_days:
        streak += 1
        day -= 1
    return streak


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
    override = (tournament.word_overrides or {}).get(str(day_number))
    word = override if override else pick_word_for_day(tournament.id, day_number, already_used)

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


async def get_tiebreak_word_queue(session: AsyncSession, tournament: Tournament, count: int = 5) -> list[dict]:
    """
    Превью первых `count` слов розыгрыша типа tiebreak — до того, как реально
    наступил соответствующий раунд, слово детерминированно выбирается по
    (tournament_id, day_number), как и обычное слово дня (см. pick_word_for_day),
    либо берётся из ручной замены (tournament.word_overrides). Как только раунд
    с этим номером дня реально создан (см. create_tiebreak_round) — слово уже
    зафиксировано и не редактируется (day-word мог быть уже сыгран).
    """
    existing_by_day = {w.day_number: w for w in await list_daily_words(session, tournament.id)}
    already_used = await _get_used_words(session, tournament.id)
    overrides = tournament.word_overrides or {}

    queue = []
    for day_number in range(1, count + 1):
        existing = existing_by_day.get(day_number)
        if existing is not None:
            queue.append({"day_number": day_number, "word": existing.word, "editable": False})
            already_used = already_used | {existing.word}
            continue
        override = overrides.get(str(day_number))
        word = override if override else pick_word_for_day(tournament.id, day_number, already_used)
        already_used = already_used | {word}
        queue.append({"day_number": day_number, "word": word, "editable": True})
    return queue


async def set_tiebreak_word_override(session: AsyncSession, tournament: Tournament, day_number: int, word: str) -> None:
    overrides = dict(tournament.word_overrides or {})
    overrides[str(day_number)] = word
    tournament.word_overrides = overrides
    session.add(tournament)
    await session.commit()


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


async def get_current_playoff_game_for_update(session: AsyncSession, match_id: int) -> PlayoffGame | None:
    """Последняя игра пары с блокировкой строки (SELECT ... FOR UPDATE) до конца
    транзакции — для отправки попытки в сетке: без замка параллельные запросы
    читали один и тот же список попыток, каждый получал подсказку, а
    записывался только последний (см. bracket_game.submit_guess).
    populate_existing — чтобы не взять устаревшее состояние из сессии."""
    result = await session.execute(
        select(PlayoffGame)
        .where(PlayoffGame.match_id == match_id)
        .order_by(PlayoffGame.game_number.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


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
    match = await session.get(PlayoffMatch, match_id)
    overrides = dict((match.word_overrides or {})) if match else {}
    override_word = overrides.pop(str(game_number), None)
    if override_word:
        word = override_word
        if match is not None:
            match.word_overrides = overrides
            session.add(match)
    else:
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


async def set_technical_loss(session: AsyncSession, game: PlayoffGame, side: str) -> PlayoffGame:
    """side — 'a' или 'b': эта сторона считается сразу проигравшей без игры
    (соперник по сетке достался ей только из-за неявки соседней пары —
    см. api/bracket_game.py::resolve_bye_if_needed)."""
    setattr(game, f"entry_{side}_technical_loss", True)
    session.add(game)
    await session.commit()
    await session.refresh(game)
    return game


async def set_playoff_word_override(session: AsyncSession, match: PlayoffMatch, game_number: int, word: str) -> None:
    """Заранее задаёт слово для игры 2 или 3 пары (на случай ничьей) — сама
    игра появится позже, лениво, только если до неё дойдёт (см. пункт бэклога
    про очередь из 3 слов)."""
    overrides = dict(match.word_overrides or {})
    overrides[str(game_number)] = word
    match.word_overrides = overrides
    session.add(match)
    await session.commit()


async def set_playoff_game_word(session: AsyncSession, game: PlayoffGame, word: str) -> PlayoffGame:
    game.word = word
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


# ---------- Словарь: слова, добавленные админом вручную ----------

async def list_added_words(session: AsyncSession) -> list[AddedWord]:
    result = await session.execute(select(AddedWord).order_by(AddedWord.added_at.desc()))
    return list(result.scalars().all())


async def add_word(session: AsyncSession, word: str) -> AddedWord:
    result = await session.execute(select(AddedWord).where(AddedWord.word == word))
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    added = AddedWord(word=word)
    session.add(added)
    await session.commit()
    await session.refresh(added)
    return added


async def remove_added_word(session: AsyncSession, added_id: int) -> str | None:
    """Возвращает слово удалённой записи (чтобы вызывающий код мог убрать его
    и из кэша словаря — см. dictionary.unregister_added_word), либо None,
    если записи с таким id не было."""
    added = await session.get(AddedWord, added_id)
    if added is None:
        return None
    word = added.word
    await session.delete(added)
    await session.commit()
    return word


async def save_playoff_guess(
    session: AsyncSession,
    game: PlayoffGame,
    side: str,
    guess: str,
    solved: bool,
    finished: bool,
) -> PlayoffGame:
    """side — 'a' или 'b', какая сторона пары делает ход."""
    from datetime import datetime
    guesses_field = f"entry_{side}_guesses"
    guesses = [*getattr(game, guesses_field), guess]
    setattr(game, guesses_field, guesses)
    now = datetime.utcnow()
    if getattr(game, f"entry_{side}_started_at") is None:
        setattr(game, f"entry_{side}_started_at", now)
    if finished:
        setattr(game, f"entry_{side}_attempts_used", len(guesses))
        setattr(game, f"entry_{side}_solved", solved)
        setattr(game, f"entry_{side}_finished_at", now)
    session.add(game)
    await session.commit()
    await session.refresh(game)
    return game
