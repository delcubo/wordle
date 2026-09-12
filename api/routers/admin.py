"""
Админ-панель: логин, глобальный список игроков, управление розыгрышами разных
типов, подключение игроков к розыгрышу, подтверждение слова дня, таблицы.
Все эндпоинты, кроме /login, защищены require_admin (см. api/admin_auth.py).
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.schemas import (
    AdminLoginRequest,
    UserCreateRequest, UserOut, UserEditRequest, UserTournamentInfo, UserArchiveRequest,
    TournamentConfigRequest, TournamentOut, TournamentSettingsUpdateRequest, TournamentPauseRequest, TournamentArchiveRequest,
    EntryCreateRequest, EntryOut, EntryEditRequest, EntryActiveRequest, EntryHiddenRequest,
    DailyWordOut, ConfirmWordRequest,
    StandingsResponse, StandingsRowOut, DailyCell,
    TiebreakRoundOut, TiebreakParticipantOut, TiebreakStartResponse, TiebreakOverrideRequest,
    PlayoffMatchOut, BracketRound1Request, MatchOverrideRequest, PlayoffWordQueueEntry, SetPlayoffWordRequest,
    DayResultOverrideRequest, DayResultOverrideResponse,
    ThemeOut, ThemeUpdateRequest,
    ExcludedWordOut, ExcludedWordCreateRequest,
    AddedWordOut, AddedWordCreateRequest,
)
from api.models import Tournament, TournamentStatus, TournamentType, User, TournamentEntry, PlayoffMatch, TiebreakRound
from api.admin_auth import check_password, create_session_token, require_admin, COOKIE_NAME
from api.dictionary import validate_manual_word, canonical_word, is_valid_word, register_added_word, unregister_added_word
from api.scoring import calculate_points
from api.tournament_time import today, day_number_for_date
from api import crud, tiebreak, bracket, bracket_game
from api.standings_view import compute_standings

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Auth ----------

@router.post("/login")
async def login(payload: AdminLoginRequest, response: Response):
    if not check_password(payload.password):
        raise HTTPException(status_code=401, detail="Неверный пароль")
    token = create_session_token()
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(_: None = Depends(require_admin)):
    return {"ok": True}


# ---------- Общие настройки сайта ----------

@router.get("/settings/theme", response_model=ThemeOut)
async def get_theme_setting(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    settings = await crud.get_app_settings(session)
    return ThemeOut(theme=settings.theme)


@router.patch("/settings/theme", response_model=ThemeOut)
async def update_theme_setting(
    payload: ThemeUpdateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Переключатель темы оформления для игроков — применяется сразу ко всем
    (см. пункт #9 бэклога), не привязан к конкретному розыгрышу."""
    if payload.theme not in ("dark", "light"):
        raise HTTPException(status_code=400, detail="Тема может быть только 'dark' или 'light'")
    settings = await crud.set_theme(session, payload.theme)
    return ThemeOut(theme=settings.theme)


# ---------- Словарь: слова, исключённые админом вручную ----------

@router.get("/dictionary/excluded", response_model=list[ExcludedWordOut])
async def get_excluded_words(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    words = await crud.list_excluded_words(session)
    return [ExcludedWordOut(id=w.id, word=w.word, excluded_at=str(w.excluded_at)) for w in words]


@router.post("/dictionary/excluded", response_model=ExcludedWordOut)
async def add_excluded_word(
    payload: ExcludedWordCreateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Исключить слово из выбора будущих слов дня (см. обсуждение источника
    словаря — способ точечно убирать странные/архаичные находки по факту игры).
    На уже назначенные слова (в т.ч. сегодняшнее) и на проверку вводимых
    попыток не влияет — см. ExcludedWord."""
    word = payload.word.strip().lower()
    if len(word) != 5:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5 букв")
    canonical = canonical_word(word) or word  # приводим е/ё к варианту из словаря, если слово там есть
    excluded = await crud.exclude_word(session, canonical)
    return ExcludedWordOut(id=excluded.id, word=excluded.word, excluded_at=str(excluded.excluded_at))


@router.delete("/dictionary/excluded/{excluded_id}")
async def remove_excluded_word(excluded_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    ok = await crud.unexclude_word(session, excluded_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Не найдено")
    return {"ok": True}


# ---------- Словарь: слова, добавленные админом вручную ----------

@router.get("/dictionary/added", response_model=list[AddedWordOut])
async def get_added_words(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    words = await crud.list_added_words(session)
    return [AddedWordOut(id=w.id, word=w.word, added_at=str(w.added_at)) for w in words]


@router.post("/dictionary/added", response_model=AddedWordOut)
async def add_added_word(
    payload: AddedWordCreateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Добавить слово, отсутствующее в словаре, но обнаруженное по факту игры
    (существительное в именительном падеже, 5 букв) — сразу становится и
    валидной попыткой, и кандидатом на будущее слово дня, без деплоя (см.
    AddedWord и dictionary.register_added_word)."""
    word = payload.word.strip().lower()
    if len(word) != 5:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5 букв")
    if not all("а" <= ch <= "я" or ch == "ё" for ch in word):
        raise HTTPException(status_code=400, detail="Слово должно состоять только из русских букв")
    if is_valid_word(word):
        raise HTTPException(status_code=400, detail="Это слово уже есть в словаре")
    added = await crud.add_word(session, word)
    register_added_word(added.word)
    return AddedWordOut(id=added.id, word=added.word, added_at=str(added.added_at))


@router.delete("/dictionary/added/{added_id}")
async def remove_added_word(added_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    word = await crud.remove_added_word(session, added_id)
    if word is None:
        raise HTTPException(status_code=404, detail="Не найдено")
    unregister_added_word(word)
    return {"ok": True}


# ---------- Users (глобальный список игроков) ----------

async def _user_tournaments(session: AsyncSession, user_id: int) -> list[UserTournamentInfo]:
    pairs = await crud.list_entries_with_tournament_for_user(session, user_id)
    return [
        UserTournamentInfo(tournament_id=t.id, title=t.title, active=e.active)
        for e, t in pairs
    ]


async def _user_out(session: AsyncSession, user: User) -> UserOut:
    return UserOut(
        id=user.id, access_token=user.access_token, admin_note=user.admin_note, created_at=str(user.created_at),
        archived=user.archived, tournaments=await _user_tournaments(session, user.id),
    )


@router.post("/users", response_model=UserOut)
async def create_user(payload: UserCreateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    note = (payload.admin_note or "").strip() or None
    if note and await crud.admin_note_taken(session, note):
        raise HTTPException(status_code=400, detail="Игрок с такой заметкой уже есть")
    user = await crud.create_user(session, note)
    return await _user_out(session, user)


@router.get("/users", response_model=list[UserOut])
async def get_users(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    users = await crud.list_users(session)
    return [await _user_out(session, u) for u in users]


@router.patch("/users/{user_id}", response_model=UserOut)
async def edit_user(user_id: int, payload: UserEditRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    note = (payload.admin_note or "").strip() or None
    if note and await crud.admin_note_taken(session, note, exclude_user_id=user_id):
        raise HTTPException(status_code=400, detail="Игрок с такой заметкой уже есть")
    user = await crud.edit_user_note(session, user_id, note)
    if user is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    return await _user_out(session, user)


@router.patch("/users/{user_id}/archive", response_model=UserOut)
async def archive_user(
    user_id: int, payload: UserArchiveRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """"Удалить" игрока (переместить в папку "Удалённые") или восстановить его
    обратно — см. пункт #12 бэклога. Ничего не удаляется физически."""
    user = await crud.set_user_archived(session, user_id, payload.archived)
    if user is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    return await _user_out(session, user)


@router.post("/users/{user_id}/disconnect", response_model=UserOut)
async def disconnect_user(user_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Отключить игрока от всех розыгрышей — в отличие от архивации, личная
    ссылка продолжает работать (игрок просто нигде не участвует)."""
    user = await crud.disconnect_user_from_all(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    return await _user_out(session, user)


@router.post("/users/{user_id}/regenerate-link", response_model=UserOut)
async def regenerate_user_link(user_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Новая персональная ссылка взамен утерянной — доступ тот же, старая
    ссылка перестаёт работать (см. пункт бэклога)."""
    user = await crud.regenerate_access_token(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    return await _user_out(session, user)


# ---------- Tournaments ----------

@router.post("/tournaments", response_model=TournamentOut)
async def create_tournament(
    payload: TournamentConfigRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    try:
        t_type = TournamentType(payload.type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неизвестный тип розыгрыша")

    if t_type in (TournamentType.standard, TournamentType.championship) and not payload.duration_days:
        raise HTTPException(status_code=400, detail="Для этого типа розыгрыша нужно указать длительность в днях")

    if payload.bracket_size is not None:
        n = payload.bracket_size
        if n <= 0 or (n & (n - 1)) != 0:
            raise HTTPException(status_code=400, detail="Размер сетки должен быть степенью двойки")
    if t_type == TournamentType.knockout and not payload.bracket_size:
        raise HTTPException(status_code=400, detail="Для розыгрыша на вылет нужно указать размер сетки")

    no_duration_types = (TournamentType.knockout, TournamentType.endless)
    tournament = Tournament(
        title=payload.title,
        type=t_type,
        start_date=payload.start_date,
        duration_days=payload.duration_days if t_type not in no_duration_types else None,
        scoring_rules=payload.scoring_rules if t_type != TournamentType.endless else None,
        skip_flag_symbol=payload.skip_flag_symbol,
        bracket_size=payload.bracket_size,
        rounds_per_match=payload.rounds_per_match,
        hashtag=(payload.hashtag or "").strip() or None,
        note=(payload.note or "").strip() or None,
        status=TournamentStatus.draft,
    )
    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    return tournament


@router.get("/tournaments", response_model=list[TournamentOut])
async def get_tournaments(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await crud.list_tournaments(session)


@router.patch("/tournaments/{tournament_id}", response_model=TournamentOut)
async def update_tournament_settings(
    tournament_id: int, payload: TournamentSettingsUpdateRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Название (чистое, без плейсхолдеров — день/стадия подставляются автоматически),
    хэштег для результата, заметка админа и, для standard/championship, длительность
    в днях — можно и увеличить, и сократить, но не меньше текущего дня. Дату
    старта можно менять, только пока розыгрыш ещё не начался."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")

    if payload.title is not None:
        tournament.title = payload.title

    if payload.hashtag is not None:
        tournament.hashtag = payload.hashtag.strip() or None

    if payload.note is not None:
        tournament.note = payload.note.strip() or None

    if payload.start_date is not None:
        if day_number_for_date(tournament.start_date, today()) >= 1:
            raise HTTPException(status_code=400, detail="Розыгрыш уже начался — дату старта менять поздно")
        if payload.start_date < today():
            raise HTTPException(status_code=400, detail="Дата старта не может быть в прошлом")
        tournament.start_date = payload.start_date

    if payload.duration_days is not None:
        if tournament.duration_days is None:
            raise HTTPException(status_code=400, detail="У этого типа розыгрыша нет длительности в днях")
        current_day = day_number_for_date(tournament.start_date, today())
        min_duration = max(current_day, 1)
        if payload.duration_days < min_duration:
            raise HTTPException(
                status_code=400,
                detail=f"Нельзя сократить меньше {min_duration} дн. — сегодняшний день должен остаться в розыгрыше",
            )
        tournament.duration_days = payload.duration_days

    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    return tournament


@router.post("/tournaments/{tournament_id}/activate", response_model=TournamentOut)
async def activate_tournament(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    # Несколько розыгрышей теперь МОГУТ быть активны одновременно — предыдущие
    # активные розыгрыши больше не завершаются автоматически при активации нового.
    # Исключение — endless: бессрочная игра одна на всех.
    if tournament.type == TournamentType.endless:
        other = await crud.get_other_active_tournament_of_type(session, TournamentType.endless, tournament.id)
        if other is not None:
            raise HTTPException(status_code=400, detail=f"Уже идёт бессрочная игра «{other.title}» — сначала завершите её")
    tournament.status = TournamentStatus.active
    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    return tournament


@router.patch("/tournaments/{tournament_id}/pause", response_model=TournamentOut)
async def pause_tournament(
    tournament_id: int, payload: TournamentPauseRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Немедленно приостанавливает розыгрыш для всех участников (или возобновляет
    его) без изменения фазы — см. пункт бэклога."""
    tournament = await crud.set_tournament_paused(session, tournament_id, payload.paused)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    return tournament


@router.patch("/tournaments/{tournament_id}/archive", response_model=TournamentOut)
async def archive_tournament(
    tournament_id: int, payload: TournamentArchiveRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Вручную переместить розыгрыш в архив (или вернуть обратно) — независимо
    от статуса, обычно применяется к приостановленным или завершённым."""
    tournament = await crud.set_tournament_archived(session, tournament_id, payload.archived)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    return tournament


# ---------- Tournament entries (подключение игрока к розыгрышу) ----------

@router.post("/tournaments/{tournament_id}/entries", response_model=EntryOut)
async def add_entry(
    tournament_id: int, payload: EntryCreateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    if user.archived:
        raise HTTPException(status_code=400, detail="Этот игрок удалён — сначала восстановите его во вкладке «Игроки»")

    existing = await crud.get_entry_including_inactive(session, tournament_id, payload.user_id)
    if existing is not None and existing.active:
        raise HTTPException(status_code=400, detail="Этот игрок уже подключён к розыгрышу")

    if (
        (existing is None or payload.callsign != existing.callsign)
        and await crud.callsign_taken(session, tournament_id, payload.callsign)
    ):
        raise HTTPException(status_code=400, detail="Этот позывной уже занят в текущем розыгрыше")

    if existing is not None:
        # игрок раньше был отключён от этого розыгрыша — подключаем обратно ту же
        # запись (и её историю попыток), а не заводим вторую
        await crud.edit_entry_callsign(session, existing.id, payload.callsign)
        await crud.set_entry_hidden(session, existing.id, payload.hidden_from_standings)
        entry = await crud.set_entry_active(session, existing.id, True)
    else:
        entry = await crud.create_entry(
            session, tournament, payload.user_id, payload.callsign, payload.hidden_from_standings
        )
    return entry


@router.get("/tournaments/{tournament_id}/entries", response_model=list[EntryOut])
async def get_entries(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await crud.list_entries(session, tournament_id)


@router.patch("/entries/{entry_id}", response_model=EntryOut)
async def edit_entry(entry_id: int, payload: EntryEditRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    if payload.callsign != entry.callsign and await crud.callsign_taken(session, entry.tournament_id, payload.callsign):
        raise HTTPException(status_code=400, detail="Этот позывной уже занят")
    updated = await crud.edit_entry_callsign(session, entry_id, payload.callsign)
    return updated


@router.post("/tournaments/{tournament_id}/entries/disconnect-all", response_model=list[EntryOut])
async def disconnect_all_entries(
    tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Отключить одной кнопкой сразу всех участников розыгрыша — не удаляет
    записи и накопленную статистику, каждого можно подключить обратно
    по отдельности (см. set_entry_active)."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    await crud.disconnect_all_entries(session, tournament_id)
    return await crud.list_entries(session, tournament_id)


@router.patch("/entries/{entry_id}/active", response_model=EntryOut)
async def set_entry_active(
    entry_id: int, payload: EntryActiveRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Отключить игрока от розыгрыша (или подключить обратно) без удаления
    записи и накопленной статистики — см. пункт #11 бэклога."""
    entry = await crud.set_entry_active(session, entry_id, payload.active)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    return entry


@router.patch("/entries/{entry_id}/hidden", response_model=EntryOut)
async def set_entry_hidden(
    entry_id: int, payload: EntryHiddenRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Учитывать/не учитывать этого участника в таблице результатов розыгрыша
    (замена глобального 'тестового' игрока — см. пункт #17 бэклога)."""
    entry = await crud.set_entry_hidden(session, entry_id, payload.hidden_from_standings)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    return entry


# ---------- Подтверждение слова дня ----------

@router.get("/tournaments/{tournament_id}/words", response_model=list[DailyWordOut])
async def get_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await crud.list_daily_words(session, tournament_id)


@router.get("/tournaments/{tournament_id}/words/upcoming", response_model=DailyWordOut)
async def get_upcoming_word(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """
    Слово на ближайший ещё не наступивший день — то, что админ может подтвердить
    или заменить. Работает и для endless (там просто нет верхней границы дней —
    см. пункт бэклога), но не для knockout — там нет слова дня вне пар сетки.
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type == TournamentType.knockout:
        raise HTTPException(status_code=400, detail="У этого типа розыгрыша нет ежедневного слова")

    current_day = day_number_for_date(tournament.start_date, today())
    next_day = max(current_day, 0) + 1  # ближайший день, который ещё не наступил
    if tournament.duration_days is not None and next_day > tournament.duration_days:
        raise HTTPException(status_code=400, detail="Розыгрыш уже завершается — новых дней не осталось")

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, next_day)
    return daily_word


@router.get("/tournaments/{tournament_id}/words/today", response_model=DailyWordOut)
async def get_today_word(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """
    Слово сегодняшнего (уже идущего) дня — чисто для справки админу (см. пункт
    #3 бэклога: "upcoming" всегда прыгает на день вперёд и никогда не показывает
    день, который уже наступил, включая самый первый день розыгрыша). Ничего
    менять тут нельзя — день уже идёт, участники уже могут по нему играть.
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type == TournamentType.knockout:
        raise HTTPException(status_code=400, detail="У этого типа розыгрыша нет слова дня")

    current_day = day_number_for_date(tournament.start_date, today())
    if current_day < 1:
        raise HTTPException(status_code=400, detail="Розыгрыш ещё не начался")
    if tournament.duration_days is not None and current_day > tournament.duration_days:
        raise HTTPException(status_code=400, detail="Розыгрыш уже завершился")

    return await crud.get_or_suggest_daily_word(session, tournament, current_day)


@router.post("/words/{daily_word_id}/confirm", response_model=DailyWordOut)
async def confirm_word(
    daily_word_id: int, payload: ConfirmWordRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    from api.models import DailyWord
    daily_word = await session.get(DailyWord, daily_word_id)
    if daily_word is None:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    if daily_word.calendar_date <= today():
        raise HTTPException(status_code=400, detail="Этот день уже наступил — слово менять поздно")

    if payload.override_word:
        already_used = {w.word for w in await crud.list_daily_words(session, daily_word.tournament_id) if w.id != daily_word.id}
        error = validate_manual_word(payload.override_word, already_used)
        if error:
            raise HTTPException(status_code=400, detail=error)
        # приводим к каноническому написанию из словаря (с ё, если оно там есть) —
        # админ мог набрать вариант с е, см. dictionary.canonical_word
        override = canonical_word(payload.override_word)
    else:
        override = None

    return await crud.confirm_daily_word(session, daily_word, override)


@router.post("/words/{daily_word_id}/reroll", response_model=DailyWordOut)
async def reroll_word(
    daily_word_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    from api.models import DailyWord
    daily_word = await session.get(DailyWord, daily_word_id)
    if daily_word is None:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    if daily_word.calendar_date <= today():
        raise HTTPException(status_code=400, detail="Этот день уже наступил — слово менять поздно")

    return await crud.reroll_daily_word(session, daily_word)


# ---------- Standings ----------

@router.get("/tournaments/{tournament_id}/standings", response_model=StandingsResponse)
async def get_standings(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.duration_days is None:
        raise HTTPException(status_code=400, detail="Для этого типа розыгрыша таблица не ведётся")

    rows = await compute_standings(session, tournament)
    return StandingsResponse(
        rows=[
            StandingsRowOut(
                participant_id=r.participant_id,
                callsign=r.callsign,
                total_points=r.total_points,
                place=r.place,
                daily=[
                    DailyCell(
                        played=d.played, points=d.points, admin_note=d.admin_note,
                        not_played_yet=d.not_played_yet, guesses=d.guesses,
                    )
                    for d in r.daily
                ],
            )
            for r in rows
        ],
        total_days=tournament.duration_days,
        current_day=max(1, min(day_number_for_date(tournament.start_date, today()), tournament.duration_days)),
        skip_flag_symbol=tournament.skip_flag_symbol,
        hashtag=tournament.hashtag,
    )


@router.post("/entries/{entry_id}/days/{day_number}/override", response_model=DayResultOverrideResponse)
async def override_day_result(
    entry_id: int, day_number: int, payload: DayResultOverrideRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """
    Ручная корректировка результата дня для одного участника — правит ошибку
    в записи или засчитывает день, который участник не мог сыграть. Таблица
    ничего отдельно не хранит — пересчитывается как обычно, уже с этим Attempt.
    """
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    tournament = await crud.get_tournament(session, entry.tournament_id)
    if tournament is None or tournament.duration_days is None:
        raise HTTPException(status_code=400, detail="Для этого розыгрыша нет дней с очками")
    if day_number < 1 or day_number > tournament.duration_days:
        raise HTTPException(status_code=400, detail=f"День должен быть от 1 до {tournament.duration_days}")
    if not (1 <= payload.attempts_used <= 6):
        raise HTTPException(status_code=400, detail="Число попыток должно быть от 1 до 6")
    note = payload.note.strip()
    if not note:
        raise HTTPException(status_code=400, detail="Нужно указать причину корректировки")

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, day_number)
    points = calculate_points(payload.attempts_used, payload.solved, tournament.scoring_rules)
    attempt = await crud.override_attempt(
        session, entry.id, daily_word.id, payload.attempts_used, payload.solved, points, note
    )
    return DayResultOverrideResponse(
        entry_id=entry.id,
        day_number=day_number,
        attempts_used=attempt.attempts_used,
        solved=attempt.solved,
        points=attempt.points,
        admin_note=attempt.admin_note,
    )


# ---------- Тай-брейк (championship) ----------

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


# ---------- Сетка плей-офф ----------

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
    """Очередь из 3 слов пары (текущее + 2 превью на случай ничьей) — см.
    пункт бэклога. С игры 4 слова снова генерируются автоматически."""
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")
    return [PlayoffWordQueueEntry(**q) for q in await bracket_game.get_word_queue(session, match)]


@router.post("/bracket/matches/{match_id}/words/{game_number}", response_model=PlayoffWordQueueEntry)
async def set_bracket_word(
    match_id: int, game_number: int, payload: SetPlayoffWordRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    if game_number not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Слово можно задать только для игр 1-3 этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    already_used = await crud.get_all_used_words(session, match.tournament_id)
    error = validate_manual_word(payload.word, already_used)
    if error:
        raise HTTPException(status_code=400, detail=error)
    word = canonical_word(payload.word) or payload.word.strip().lower()

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None:
        if existing.calendar_date <= today():
            raise HTTPException(status_code=400, detail="Эта игра уже наступила — слово менять поздно")
        await crud.set_playoff_game_word(session, existing, word)
    else:
        await crud.set_playoff_word_override(session, match, game_number, word)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))


@router.post("/bracket/matches/{match_id}/words/{game_number}/reroll", response_model=PlayoffWordQueueEntry)
async def reroll_bracket_word(
    match_id: int, game_number: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """"Предложить другое слово" для пары сетки — то же, что реролл обычного
    слова дня, только для слота очереди (см. пункт бэклога)."""
    if game_number not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Слово можно задать только для игр 1-3 этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None and existing.calendar_date <= today():
        raise HTTPException(status_code=400, detail="Эта игра уже наступила — слово менять поздно")

    await bracket_game.reroll_word_queue_slot(session, match, game_number)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))
