"""
Админ-панель: логин, глобальный список игроков, управление розыгрышами разных
типов, подключение игроков к розыгрышу, подтверждение слова дня, таблицы.
Все эндпоинты, кроме /login, защищены require_admin (см. api/admin_auth.py).
"""
import asyncio
from collections import namedtuple
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.schemas import (
    AdminLoginRequest,
    UserCreateRequest, UserOut, UserEditRequest, UserTournamentInfo, UserArchiveRequest,
    TournamentConfigRequest, TournamentOut, TournamentSettingsUpdateRequest, TournamentPauseRequest, TournamentArchiveRequest,
    EntryCreateRequest, EntryOut, EntryEditRequest, EntryActiveRequest, EntryHiddenRequest,
    EntriesTransferRequest, EntriesTransferResponse,
    DailyWordOut, ConfirmWordRequest,
    StandingsResponse, StandingsRowOut, DailyCell,
    TieGroupMember, TieGroupOut, TieGroupsResponse, TieResolutionsRequest,
    TiebreakRoundOut, TiebreakParticipantOut, TiebreakStartResponse, TiebreakOverrideRequest,
    TiebreakWordQueueEntry, SetTiebreakWordRequest, TiebreakResultsOut,
    PlayoffMatchOut, BracketRound1Request, MatchOverrideRequest, PlayoffWordQueueEntry, SetPlayoffWordRequest,
    DayResultOverrideRequest, DayResultOverrideResponse,
    ThemeOut, ThemeUpdateRequest,
    ExcludedWordOut, ExcludedWordCreateRequest,
    AddedWordOut, AddedWordCreateRequest,
    MarathonWordOut, MarathonStandingsOut, MarathonPlayerWordsOut, SlotLengthRequest, WordPlanRequest,
    TeamCreateRequest, TeamOut, EntryTeamRequest, TeamStandingsOut,
    TeamTieGroupsResponse, TeamTieGroupOut, TeamTieMember, TeamTieResolutionsRequest, TeamTiebreakCreateRequest,
    TeamWordDayOut, TiebreakTeamResultsOut,
)
from api.models import Tournament, TournamentStatus, TournamentType, User, TournamentEntry, PlayoffMatch, TiebreakRound, Team
from api.admin_auth import (
    check_password, create_session_token, require_admin, COOKIE_NAME, SESSION_MAX_AGE_SECONDS,
    client_ip, login_retry_after, record_login_failure, clear_login_failures,
)
from api.dictionary import (
    validate_manual_word, canonical_word, is_valid_word, register_added_word, unregister_added_word, SUPPORTED_LENGTHS,
)
from api.scoring import calculate_points
from api.tournament_time import today, day_number_for_date, effective_status
from api import crud, tiebreak, bracket, bracket_game, notify, marathon, teams
from api import word_plan as wp
from api.standings_view import compute_standings

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Auth ----------

@router.post("/login")
async def login(payload: AdminLoginRequest, request: Request, response: Response):
    ip = client_ip(request)
    retry_after = login_retry_after(ip)
    if retry_after:
        minutes = max(1, (retry_after + 59) // 60)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много неудачных попыток входа. Повторите через {minutes} мин.",
            headers={"Retry-After": str(retry_after)},
        )
    if not check_password(payload.password):
        record_login_failure(ip)
        # небольшая задержка замедляет подбор, не блокируя остальные запросы
        await asyncio.sleep(1)
        raise HTTPException(status_code=401, detail="Неверный пароль")
    clear_login_failures(ip)
    token = create_session_token()
    # secure — только когда запрос реально пришёл по HTTPS (за прокси Railway это
    # видно по X-Forwarded-Proto), чтобы локальная разработка по http не ломалась
    is_https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="strict", secure=is_https, max_age=SESSION_MAX_AGE_SECONDS
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(_: None = Depends(require_admin)):
    return {"ok": True}


@router.post("/telegram/test")
async def telegram_test(_: None = Depends(require_admin)):
    """Тестовое сообщение в Telegram — чтобы проверить, что бот и chat_id
    настроены (см. api/notify.py), не дожидаясь настоящей партии игрока."""
    if not notify.is_configured():
        return {"ok": False, "detail": "Не заданы переменные TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID на сервере"}
    ok, detail = await notify.send_admin_message("✅ Тест: уведомления из Вордли работают")
    return {"ok": ok, "detail": "Сообщение отправлено" if ok else detail}


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
    if len(word) not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5, 6 или 7 букв")
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
    if len(word) not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5, 6 или 7 букв")
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

async def _user_out(session: AsyncSession, user: User) -> UserOut:
    pairs = await crud.list_entries_with_tournament_for_user(session, user.id)
    last_callsign = max(pairs, key=lambda p: p[0].joined_at)[0].callsign if pairs else None
    return UserOut(
        id=user.id, access_token=user.access_token, admin_note=user.admin_note, created_at=str(user.created_at),
        archived=user.archived,
        tournaments=[UserTournamentInfo(tournament_id=t.id, title=t.title, active=e.active) for e, t in pairs],
        last_callsign=last_callsign,
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

def _tournament_out(tournament: Tournament) -> TournamentOut:
    """status — вычисленный (см. api.tournament_time.effective_status), а не
    сырое поле из БД: ручной активации больше нет, draft/active выводятся из
    даты старта на лету (см. пункт бэклога)."""
    return TournamentOut.model_validate(tournament).model_copy(update={"status": effective_status(tournament).value})


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

    if payload.word_length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина слов должна быть 5, 6 или 7 букв")

    if t_type == TournamentType.marathon:
        if payload.words_count is None or not (marathon.MIN_WORDS <= payload.words_count <= marathon.MAX_WORDS):
            raise HTTPException(
                status_code=400, detail=f"Число слов должно быть от {marathon.MIN_WORDS} до {marathon.MAX_WORDS}"
            )
        if payload.end_date is not None and payload.end_date < payload.start_date:
            raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты старта")

    if t_type == TournamentType.tiebreak:
        if payload.end_date is not None and payload.end_date < payload.start_date:
            raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты старта")
    elif t_type != TournamentType.marathon and payload.end_date is not None:
        raise HTTPException(status_code=400, detail="Дата окончания задаётся только у марафона и тай-брейка")

    if t_type == TournamentType.endless:
        # ручной активации больше нет — проверяем сразу при создании, чтобы не
        # завести вторую бессрочную игру, которая рано или поздно (по дате
        # старта) сама начнёт выдавать слова параллельно с текущей
        other = await crud.get_other_active_tournament_of_type(session, TournamentType.endless)
        if other is not None:
            raise HTTPException(status_code=400, detail=f"Уже идёт бессрочная игра «{other.title}» — сначала завершите её")

    no_duration_types = (TournamentType.knockout, TournamentType.endless, TournamentType.tiebreak, TournamentType.marathon)
    tournament = Tournament(
        title=payload.title,
        type=t_type,
        start_date=payload.start_date,
        duration_days=payload.duration_days if t_type not in no_duration_types else None,
        scoring_rules=(
            payload.scoring_rules
            if t_type not in (TournamentType.endless, TournamentType.tiebreak, TournamentType.marathon) else None
        ),
        words_count=payload.words_count if t_type == TournamentType.marathon else None,
        end_date=payload.end_date if t_type in (TournamentType.marathon, TournamentType.tiebreak) else None,
        individual_words=bool(payload.individual_words) and t_type == TournamentType.marathon,
        word_length=payload.word_length,
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
    if t_type == TournamentType.marathon and not tournament.individual_words:
        await marathon.ensure_words(session, tournament)  # общие слова видны админу сразу
    return _tournament_out(tournament)


@router.put("/tournaments/{tournament_id}/word-plan", response_model=TournamentOut)
async def put_word_plan(
    tournament_id: int, payload: WordPlanRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """План длин слов по позициям (api/word_plan.py): марафон — по номеру слова,
    плей-офф — по стадии и номеру игры, тай-брейк — по глубине раунда. Полностью
    заменяет прежний план (пустой — сброс на базовую длину). Влияет только на ещё не
    созданные слова; у марафона не начатые слова, предложенные системой, тут же
    заменяются словами нужной длины, а подтверждённые/введённые вручную остаются."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    try:
        plan = wp.validate_plan(payload.plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if plan:
        if "marathon" in plan:
            if tournament.type != TournamentType.marathon:
                raise HTTPException(status_code=400, detail="План по номерам слов — только для марафона")
            if len(plan["marathon"]) > (tournament.words_count or 0):
                raise HTTPException(status_code=400, detail="В плане больше длин, чем слов в марафоне")
        if "playoff" in plan and tournament.type not in (TournamentType.championship, TournamentType.knockout):
            raise HTTPException(status_code=400, detail="План по стадиям — только для розыгрышей с сеткой плей-офф")
        if "tiebreak" in plan and tournament.type not in (TournamentType.tiebreak, TournamentType.championship):
            raise HTTPException(status_code=400, detail="План по раундам — только для тай-брейка")
    tournament.word_plan = plan
    session.add(tournament)
    await session.commit()
    if tournament.type == TournamentType.marathon:
        await marathon.apply_lengths(session, tournament)
    await session.refresh(tournament)
    return _tournament_out(tournament)


@router.get("/tournaments", response_model=list[TournamentOut])
async def get_tournaments(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return [_tournament_out(t) for t in await crud.list_tournaments(session)]


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

    if payload.notify_admin is not None:
        tournament.notify_admin = payload.notify_admin

    if (payload.words_count is not None or payload.individual_words is not None) and tournament.type != TournamentType.marathon:
        raise HTTPException(status_code=400, detail="Число слов и режим слов настраиваются только у марафона")
    if (payload.end_date is not None or payload.clear_end_date) and tournament.type not in (
        TournamentType.marathon, TournamentType.tiebreak
    ):
        raise HTTPException(status_code=400, detail="Дата окончания настраивается только у марафона и тай-брейка")

    if payload.teams_enabled is not None:
        if tournament.type not in (TournamentType.marathon, TournamentType.tiebreak):
            raise HTTPException(status_code=400, detail="Командный зачёт есть только у марафона и тай-брейка")
        if (
            tournament.type == TournamentType.tiebreak and payload.teams_enabled != bool(tournament.teams_enabled)
            and await crud.list_root_tiebreak_rounds(session, tournament.id)
        ):
            raise HTTPException(status_code=400, detail="Тай-брейк уже начался — режим команд менять поздно")
        tournament.teams_enabled = payload.teams_enabled

    if payload.individual_words is not None and payload.individual_words != bool(tournament.individual_words):
        try:
            await marathon.convert_mode(session, tournament, payload.individual_words)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if payload.words_count is not None and payload.words_count != tournament.words_count:
        new_count = payload.words_count
        if not (marathon.MIN_WORDS <= new_count <= marathon.MAX_WORDS):
            raise HTTPException(
                status_code=400, detail=f"Число слов должно быть от {marathon.MIN_WORDS} до {marathon.MAX_WORDS}"
            )
        if new_count > (tournament.words_count or 0):
            tournament.words_count = new_count
            session.add(tournament)
            await session.commit()
            await marathon.ensure_all(session, tournament)
        else:
            # убрать можно только слова, которые никто не начал
            for dw in await crud.list_daily_words(session, tournament.id):
                if dw.day_number > new_count and await marathon.word_started(session, dw.id):
                    raise HTTPException(
                        status_code=400, detail=f"Слово {dw.day_number} уже начали отгадывать — убрать его нельзя"
                    )
            for dw in await crud.list_daily_words(session, tournament.id):
                if dw.day_number > new_count:
                    await session.delete(dw)
            tournament.words_count = new_count

    if payload.end_date is not None:
        if payload.end_date < tournament.start_date:
            raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты старта")
        tournament.end_date = payload.end_date
    elif payload.clear_end_date:
        tournament.end_date = None

    if payload.third_place_match is not None and payload.third_place_match != tournament.third_place_match:
        try:
            await bracket_game.set_third_place_match(session, tournament, payload.third_place_match)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if payload.first_place is not None:
        if tournament.type != TournamentType.tiebreak:
            raise HTTPException(status_code=400, detail="Первое место настраивается только у тай-брейка")
        if not (1 <= payload.first_place <= 9999):
            raise HTTPException(status_code=400, detail="Место должно быть числом от 1 до 9999")
        tournament.first_place = payload.first_place

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
    return _tournament_out(tournament)


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
    return _tournament_out(tournament)


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
    return _tournament_out(tournament)


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
    entries = await crud.list_entries(session, tournament_id)
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None or tournament.type not in (TournamentType.endless, TournamentType.standard, TournamentType.knockout):
        return entries
    attempts_by_entry = await crud.get_entries_played_today(session, tournament)
    game_today_ids = None
    if tournament.type == TournamentType.knockout:
        game_today_ids = (await crud.get_knockout_today_status(session, tournament))[1]

    def _iso_utc(naive_dt):
        # started_at/finished_at хранятся как наивный UTC (datetime.utcnow) —
        # добавляем явную зону, иначе браузер разобрал бы ISO-строку без
        # смещения как локальное время и время начала/попытки съехало бы.
        return naive_dt.replace(tzinfo=timezone.utc).isoformat() if naive_dt else None

    return [
        EntryOut(
            id=e.id, user_id=e.user_id, callsign=e.callsign, joined_on_day=e.joined_on_day,
            active=e.active, hidden_from_standings=e.hidden_from_standings,
            played_today=e.id in attempts_by_entry,
            played_today_attempts=(attempts_by_entry.get(e.id) or {}).get("attempts_used"),
            played_today_started_at=_iso_utc((attempts_by_entry.get(e.id) or {}).get("started_at")),
            played_today_finished_at=_iso_utc((attempts_by_entry.get(e.id) or {}).get("finished_at")),
            has_game_today=None if game_today_ids is None else e.id in game_today_ids,
        )
        for e in entries
    ]


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


@router.post("/tournaments/{tournament_id}/entries/add-all", response_model=list[EntryOut])
async def add_all_entries(
    tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Подключить одной кнопкой сразу всех зарегистрированных игроков платформы
    — чтобы не добавлять по одному вручную (см. crud.add_all_users)."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    await crud.add_all_users(session, tournament)
    return await crud.list_entries(session, tournament_id)


@router.post("/tournaments/{tournament_id}/entries/transfer", response_model=EntriesTransferResponse)
async def transfer_entries(
    tournament_id: int, payload: EntriesTransferRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Массовый переброс выбранных игроков из этого розыгрыша в другой — см.
    crud.transfer_entries. Best-effort: игрока с занятым в целевом розыгрыше
    позывным просто пропускает (ничего для него не меняет), остальных
    переносит как обычно — причины отказов возвращаются в ответе."""
    from_tournament = await crud.get_tournament(session, tournament_id)
    if from_tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if payload.to_tournament_id == tournament_id:
        raise HTTPException(status_code=400, detail="Целевой розыгрыш совпадает с исходным")
    to_tournament = await crud.get_tournament(session, payload.to_tournament_id)
    if to_tournament is None:
        raise HTTPException(status_code=404, detail="Целевой розыгрыш не найден")
    if to_tournament.archived:
        raise HTTPException(status_code=400, detail="Целевой розыгрыш в архиве")
    if not payload.entry_ids:
        raise HTTPException(status_code=400, detail="Не выбрано ни одного игрока")
    results = await crud.transfer_entries(session, from_tournament, to_tournament, payload.entry_ids)
    return EntriesTransferResponse(results=results)


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


@router.post("/entries/{entry_id}/reset-today")
async def reset_entry_today(entry_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Сбросить попытку участника за сегодняшний день целиком — как будто он
    ещё не играл сегодня (не для исправления результата, для полного
    повторного шанса — см. crud.reset_todays_attempt). Не применимо к
    knockout и к дням вне диапазона розыгрыша."""
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    tournament = await crud.get_tournament(session, entry.tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    reset = await crud.reset_todays_attempt(session, entry, tournament)
    if not reset:
        raise HTTPException(status_code=400, detail="Сегодня участник ещё не играл — нечего сбрасывать")
    return {"ok": True}


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


# ---------- Марафон ----------

async def _get_marathon(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type != TournamentType.marathon:
        raise HTTPException(status_code=400, detail="Это не марафон")
    return tournament


@router.get("/tournaments/{tournament_id}/marathon/words", response_model=list[MarathonWordOut])
async def get_marathon_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Все слова марафона по порядку; менять (confirm/reroll у /words/{id}) можно те,
    которые никто ещё не начал отгадывать."""
    tournament = await _get_marathon(session, tournament_id)
    if tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона личные наборы слов — см. individual-words")
    return await marathon.words_overview(session, tournament)


# ---------- Марафон: команды и командный зачёт (api/teams.py) ----------

async def _team_out(session: AsyncSession, team: Team) -> TeamOut:
    members = [e for e in await crud.list_entries(session, team.tournament_id) if e.team_id == team.id]
    return TeamOut(id=team.id, tournament_id=team.tournament_id, name=team.name, members_count=len(members))


async def _get_team_tournament(session: AsyncSession, tournament_id: int) -> Tournament:
    """Розыгрыш, в котором бывают команды: марафон или тай-брейк."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type not in (TournamentType.marathon, TournamentType.tiebreak):
        raise HTTPException(status_code=400, detail="Команды есть только в марафоне и тай-брейке")
    return tournament


@router.get("/tournaments/{tournament_id}/teams", response_model=list[TeamOut])
async def get_teams(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    await _get_team_tournament(session, tournament_id)
    return [await _team_out(session, t) for t in await teams.list_teams(session, tournament_id)]


@router.post("/tournaments/{tournament_id}/teams", response_model=TeamOut)
async def create_team(
    tournament_id: int, payload: TeamCreateRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    tournament = await _get_team_tournament(session, tournament_id)
    try:
        team = await teams.create_team(session, tournament, payload.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _team_out(session, team)


@router.patch("/teams/{team_id}", response_model=TeamOut)
async def rename_team(
    team_id: int, payload: TeamCreateRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    try:
        team = await teams.rename_team(session, team, payload.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _team_out(session, team)


@router.delete("/teams/{team_id}")
async def delete_team(team_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Удалить команду: её участники остаются в розыгрыше без команды."""
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Команда не найдена")
    await teams.delete_team(session, team)
    return {"ok": True}


@router.put("/entries/{entry_id}/team", response_model=EntryOut)
async def set_entry_team(
    entry_id: int, payload: EntryTeamRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Поместить участника в команду (team_id=null — убрать из команды). Состав можно менять в
    любой момент: таблица считается на лету."""
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    tournament = await crud.get_tournament(session, entry.tournament_id)
    if tournament is None or tournament.type not in (TournamentType.marathon, TournamentType.tiebreak):
        raise HTTPException(status_code=400, detail="Команды есть только в марафоне и тай-брейке")
    if tournament.type == TournamentType.tiebreak and await crud.list_root_tiebreak_rounds(session, tournament.id):
        raise HTTPException(status_code=400, detail="Тай-брейк уже начался — состав команд менять поздно")
    try:
        return await teams.assign_entry(session, entry, payload.team_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/tournaments/{tournament_id}/marathon/team-standings", response_model=TeamStandingsOut)
async def get_team_standings(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Командная таблица марафона: среднее число попыток на слово (api/teams.py)."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.teams_enabled:
        raise HTTPException(status_code=400, detail="В этом марафоне не включён командный зачёт")
    return await teams.compute_team_standings(session, tournament)


async def _team_tie_view(session: AsyncSession, tournament: Tournament) -> TeamTieGroupsResponse:
    if not tournament.teams_enabled:
        return TeamTieGroupsResponse(can_resolve=False, reason="В этом марафоне не включён командный зачёт")
    return TeamTieGroupsResponse(
        can_resolve=True,
        groups=[
            TeamTieGroupOut(**{**g, "members": [TeamTieMember(**m) for m in g["members"]]})
            for g in await teams.tie_groups(session, tournament)
        ],
    )


@router.get("/tournaments/{tournament_id}/team-tie-groups", response_model=TeamTieGroupsResponse)
async def get_team_tie_groups(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await _team_tie_view(session, await _get_marathon(session, tournament_id))


@router.post("/tournaments/{tournament_id}/team-tie-groups/create-tiebreak", response_model=TournamentOut)
async def create_team_tiebreak(
    tournament_id: int, payload: TeamTiebreakCreateRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Создать командный тай-брейк для группы команд с общим местом: новый розыгрыш с теми же
    командами и игроками; потом разбор ничьих сам подскажет порядок по его итогам."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.teams_enabled:
        raise HTTPException(status_code=400, detail="В этом марафоне не включён командный зачёт")
    if payload.start_date is not None and payload.start_date < today():
        raise HTTPException(status_code=400, detail="Дата старта не может быть в прошлом")
    try:
        new = await teams.create_tiebreak_for_group(session, tournament, payload.place, payload.start_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _tournament_out(new)


@router.put("/tournaments/{tournament_id}/team-tie-resolutions", response_model=TeamTieGroupsResponse)
async def put_team_tie_resolutions(
    tournament_id: int, payload: TeamTieResolutionsRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Порядок команд с общим местом (полностью заменяет прежний набор; пустой список — сброс).
    Каждый порядок должен в точности совпадать по составу с одной из текущих групп."""
    tournament = await _get_marathon(session, tournament_id)
    view = await _team_tie_view(session, tournament)
    if not view.can_resolve:
        raise HTTPException(status_code=400, detail=view.reason)
    group_sets = {frozenset(m.team_id for m in g.members) for g in view.groups}
    cleaned: list[dict] = []
    seen: set[frozenset] = set()
    for item in payload.resolutions:
        key = frozenset(item.team_ids)
        if len(item.team_ids) != len(key) or key not in group_sets or key in seen:
            raise HTTPException(status_code=400, detail="Порядок не соответствует ни одной из групп с общим местом")
        seen.add(key)
        cleaned.append({"team_ids": list(item.team_ids), "source": item.source.strip()[:200]})
    tournament.team_tie_resolutions = cleaned or None
    session.add(tournament)
    await session.commit()
    return await _team_tie_view(session, tournament)


@router.get("/tournaments/{tournament_id}/marathon/standings", response_model=MarathonStandingsOut)
async def get_marathon_standings(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Сводная таблица марафона: попытки по каждому слову, пройдено слов, сумма попыток, место."""
    tournament = await _get_marathon(session, tournament_id)
    return await marathon.compute_standings(session, tournament)


@router.post("/tournaments/{tournament_id}/marathon/word-length", response_model=TournamentOut)
async def set_marathon_word_length(
    tournament_id: int, number: int, payload: SlotLengthRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сменить длину слова марафона с номером `number` (query-параметр): слова этой
    позиции, которые никто ещё не начал (у всех участников при личных наборах),
    заменяются словами нужной длины; план длин обновляется."""
    tournament = await _get_marathon(session, tournament_id)
    try:
        await marathon.set_position_length(session, tournament, number, payload.length)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await session.refresh(tournament)
    return _tournament_out(tournament)


@router.get("/tournaments/{tournament_id}/marathon/individual-words", response_model=list[MarathonPlayerWordsOut])
async def get_marathon_individual_words(
    tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Личные наборы слов всех подключённых участников (если режим личных слов включён)."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона общие слова — см. marathon/words")
    return await marathon.individual_overview(session, tournament)


@router.post("/tournaments/{tournament_id}/marathon/individual-words/regenerate")
async def regenerate_all_individual_words(
    tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Заново подобрать все ещё не начатые слова у всех участников."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона общие слова")
    return {"replaced": await marathon.regenerate_all(session, tournament)}


@router.post("/tournaments/{tournament_id}/marathon/individual-words/{entry_id}/regenerate")
async def regenerate_entry_individual_words(
    tournament_id: int, entry_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Заново подобрать все ещё не начатые слова одного участника."""
    tournament = await _get_marathon(session, tournament_id)
    if not tournament.individual_words:
        raise HTTPException(status_code=400, detail="У этого марафона общие слова")
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None or entry.tournament_id != tournament.id:
        raise HTTPException(status_code=404, detail="Участник не найден")
    return {"replaced": await marathon.regenerate_entry_words(session, tournament, entry_id)}


# ---------- Подтверждение слова дня ----------

@router.get("/tournaments/{tournament_id}/words", response_model=list[DailyWordOut])
async def get_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await crud.list_daily_words(session, tournament_id)


@router.get("/tournaments/{tournament_id}/words/upcoming", response_model=DailyWordOut)
async def get_upcoming_word(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """
    Слово на ближайший ещё не наступивший день — то, что админ может подтвердить
    или заменить. Работает и для endless (там просто нет верхней границы дней —
    см. пункт бэклога), но не для knockout — там нет слова дня вне пар сетки, и
    не для tiebreak — там день не календарный, а раундовый (см. crud.get_tiebreak_word_queue),
    и предсоздание "завтрашнего" слова тут сбило бы нумерацию дней раундов.
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type in (TournamentType.knockout, TournamentType.tiebreak, TournamentType.marathon):
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
    день, который уже наступил, включая самый первый день розыгрыша). Менять
    слово можно только в бессрочной игре и пока никто не начал партию (editable).
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type in (TournamentType.knockout, TournamentType.tiebreak, TournamentType.marathon):
        raise HTTPException(status_code=400, detail="У этого типа розыгрыша нет слова дня")

    current_day = day_number_for_date(tournament.start_date, today())
    if current_day < 1:
        raise HTTPException(status_code=400, detail="Розыгрыш ещё не начался")
    if tournament.duration_days is not None and current_day > tournament.duration_days:
        raise HTTPException(status_code=400, detail="Розыгрыш уже завершился")

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, current_day)
    out = DailyWordOut.model_validate(daily_word)
    out.editable = await _daily_word_editable(session, daily_word)
    return out


async def _daily_word_editable(session: AsyncSession, daily_word) -> bool:
    """Слово можно менять до наступления его дня. В бессрочной и стандартной
    играх — ещё и в сам день, пока никто не начал партию (слово игроку не
    показывается до конца партии, поэтому без единой догадки замена ничего не
    ломает)."""
    tournament = await crud.get_tournament(session, daily_word.tournament_id)
    if tournament is not None and tournament.type == TournamentType.marathon:
        # слова марафона нет смысла привязывать к дате: меняется, пока его никто не начал
        return not await crud.daily_word_has_attempts(session, daily_word.id)
    if daily_word.calendar_date > today():
        return True
    if daily_word.calendar_date < today():
        return False
    if tournament is None or tournament.type not in (TournamentType.endless, TournamentType.standard):
        return False
    return not await crud.daily_word_has_attempts(session, daily_word.id)


async def _word_locked_detail(session: AsyncSession, daily_word) -> str:
    tournament = await crud.get_tournament(session, daily_word.tournament_id)
    if tournament is not None and tournament.type == TournamentType.marathon:
        return "Это слово уже начали отгадывать — менять поздно"
    return "Этот день уже наступил — слово менять поздно"


@router.post("/words/{daily_word_id}/confirm", response_model=DailyWordOut)
async def confirm_word(
    daily_word_id: int, payload: ConfirmWordRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    from api.models import DailyWord
    daily_word = await session.get(DailyWord, daily_word_id)
    if daily_word is None:
        raise HTTPException(status_code=404, detail="Слово не найдено")

    if not await _daily_word_editable(session, daily_word):
        raise HTTPException(status_code=400, detail=await _word_locked_detail(session, daily_word))

    if payload.override_word:
        # в личных наборах марафона повтор слова ДРУГОГО участника допустим — запрещён только повтор внутри набора
        already_used = {
            w.word for w in await crud.list_daily_words(session, daily_word.tournament_id)
            if w.id != daily_word.id and w.entry_id == daily_word.entry_id
        }
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

    if not await _daily_word_editable(session, daily_word):
        raise HTTPException(status_code=400, detail=await _word_locked_detail(session, daily_word))

    return await crud.reroll_daily_word(session, daily_word)


# ---------- Standings ----------

@router.get("/tournaments/{tournament_id}/standings", response_model=StandingsResponse)
async def get_standings(
    tournament_id: int, as_of_day: int | None = None,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """
    as_of_day — показать таблицу по состоянию на конкретный уже полностью
    прошедший день (выбор дня в панели — см. пункт бэклога: так админ сам
    решает, копировать ли live-таблицу с ещё не всеми сыгравшими сегодня, или
    зафиксированный снимок прошлого дня). Без as_of_day — обычная live-таблица,
    включает сегодняшний день, если он уже сыгран, как и раньше.

    last_completed_day (в ответе всегда, независимо от as_of_day) — для
    построения списка дней, доступных для выбора на фронте.
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.duration_days is None:
        raise HTTPException(status_code=400, detail="Для этого типа розыгрыша таблица не ведётся")

    raw_day = day_number_for_date(tournament.start_date, today())
    # если розыгрыш уже целиком завершён (сегодня позже последнего дня),
    # завершены все дни; иначе последний завершённый день — вчерашний
    # относительно текущего (сегодняшний ещё идёт)
    last_completed_day = tournament.duration_days if raw_day > tournament.duration_days else max(0, raw_day - 1)

    if as_of_day is not None:
        if as_of_day < 1 or as_of_day > last_completed_day:
            raise HTTPException(status_code=400, detail="Этот день ещё не завершён полностью")
        max_day = as_of_day
        total_days = as_of_day
        current_day = as_of_day
    else:
        max_day = None
        total_days = tournament.duration_days
        current_day = max(1, min(raw_day, tournament.duration_days))

    rows = await compute_standings(session, tournament, max_day=max_day)
    return StandingsResponse(
        rows=[
            StandingsRowOut(
                participant_id=r.participant_id,
                callsign=r.callsign,
                total_points=r.total_points,
                place=r.place,
                tie_resolved=r.tie_resolved,
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
        total_days=total_days,
        current_day=current_day,
        last_completed_day=last_completed_day,
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


_TieRow = namedtuple("_TieRow", "entry_id callsign place points summary")


async def _tie_groups_view(session: AsyncSession, tournament: Tournament) -> TieGroupsResponse:
    """
    Группы с общим местом в итоговой таблице стандартного розыгрыша или марафона
    (без учёта уже применённых порядков) + для каждой — предложение по результатам
    тай-брейка: розыгрыш типа "Тай-брейк" с в точности теми же игроками
    (сопоставление по человеку, а не по позывному), если он уже расставил все
    места. Нужно для окончательной таблицы без разделённых мест.
    Стандартный разбирается по завершении розыгрыша; марафон — в любой момент
    (устаревший порядок при изменении состава группы просто игнорируется).
    """
    if tournament.type == TournamentType.marathon:
        data = await marathon.compute_standings(session, tournament, apply_tie_resolutions=False)
        rows = [
            _TieRow(
                r["entry_id"], r["callsign"], r["place"], r["total_attempts"],
                f"{r['words_done']}/{data['words_count']} слов · {r['total_attempts']} попыток",
            )
            for r in data["rows"]
        ]
    elif tournament.type == TournamentType.standard and tournament.duration_days is not None:
        if day_number_for_date(tournament.start_date, today()) <= tournament.duration_days:
            return TieGroupsResponse(can_resolve=False, reason="Розыгрыш ещё не завершён — ничьи разбираются по его итогам")
        rows = [
            _TieRow(r.participant_id, r.callsign, r.place, r.total_points, None)
            for r in await compute_standings(session, tournament, apply_tie_resolutions=False)
        ]
    else:
        return TieGroupsResponse(
            can_resolve=False, reason="Разбор ничьих доступен только для стандартного розыгрыша и марафона"
        )
    entries = {e.id: e for e in await crud.list_entries(session, tournament.id)}
    applied = {frozenset(r["entry_ids"]): r for r in (tournament.tie_resolutions or [])}
    # неархивные тай-брейки первыми (list_tournaments уже идёт от новых к старым)
    tiebreaks = sorted(
        [t for t in await crud.list_tournaments(session) if t.type == TournamentType.tiebreak],
        key=lambda t: t.archived,
    )
    results_cache: dict[int, dict] = {}

    groups: list[TieGroupOut] = []
    seen_places: set[str] = set()
    for row in rows:
        if "-" not in row.place or row.place in seen_places:
            continue
        seen_places.add(row.place)
        member_rows = [r for r in rows if r.place == row.place]
        member_ids = [r.entry_id for r in member_rows]
        user_by_entry = {eid: entries[eid].user_id for eid in member_ids}
        user_set = set(user_by_entry.values())

        group = TieGroupOut(
            place=row.place, points=row.points, summary=row.summary,
            members=[TieGroupMember(entry_id=r.entry_id, callsign=r.callsign) for r in member_rows],
        )

        found = None
        for t in tiebreaks:
            t_entries = await crud.list_entries(session, t.id)
            if {e.user_id for e in t_entries} == user_set:
                found = (t, t_entries)
                break
        if found is None:
            group.suggestion_note = "Подходящий тай-брейк (с тем же составом игроков) не найден — расставьте порядок вручную"
        else:
            t, t_entries = found
            if t.id not in results_cache:
                results_cache[t.id] = await tiebreak.build_results(session, t)
            entry_user = {e.id: e.user_id for e in t_entries}
            place_by_user = {
                entry_user[r["entry_id"]]: r["place"] for r in results_cache[t.id]["rows"] if r["entry_id"] in entry_user
            }
            places = [place_by_user.get(u) for u in user_set]
            if all(p and "-" not in p for p in places) and len(set(places)) == len(places):
                entry_by_user = {user_by_entry[eid]: eid for eid in member_ids}
                ordered_users = sorted(user_set, key=lambda u: int(place_by_user[u]))
                group.suggested_order = [entry_by_user[u] for u in ordered_users]
                group.suggested_source = t.title
            else:
                group.suggestion_note = f"Тай-брейк «{t.title}» ещё не определил все места"

        current = applied.get(frozenset(member_ids))
        if current:
            group.applied_order = current["entry_ids"]
            group.applied_source = current.get("source") or None
        groups.append(group)
    return TieGroupsResponse(can_resolve=True, groups=groups)


@router.get("/tournaments/{tournament_id}/tie-groups", response_model=TieGroupsResponse)
async def get_tie_groups(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    return await _tie_groups_view(session, tournament)


@router.put("/tournaments/{tournament_id}/tie-resolutions", response_model=TieGroupsResponse)
async def put_tie_resolutions(
    tournament_id: int, payload: TieResolutionsRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сохраняет окончательный порядок для групп с общим местом (полностью заменяя
    прежний набор; пустой список — сброс). Каждый порядок должен в точности
    совпадать по составу с одной из текущих групп."""
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    view = await _tie_groups_view(session, tournament)
    if not view.can_resolve:
        raise HTTPException(status_code=400, detail=view.reason)

    group_sets = {frozenset(m.entry_id for m in g.members) for g in view.groups}
    cleaned: list[dict] = []
    seen: set[frozenset] = set()
    for item in payload.resolutions:
        key = frozenset(item.entry_ids)
        if len(item.entry_ids) != len(key) or key not in group_sets or key in seen:
            raise HTTPException(status_code=400, detail="Порядок не соответствует ни одной из групп с общим местом")
        seen.add(key)
        cleaned.append({"entry_ids": list(item.entry_ids), "source": item.source.strip()[:200]})

    tournament.tie_resolutions = cleaned or None
    session.add(tournament)
    await session.commit()
    return await _tie_groups_view(session, tournament)


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


# ---------- Тай-брейк (тип розыгрыша целиком) ----------

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
    """Очередь слов пары (текущее + превью на случай ничьей, WORD_QUEUE_SIZE штук).
    Дальше слова снова генерируются автоматически."""
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")
    return [PlayoffWordQueueEntry(**q) for q in await bracket_game.get_word_queue(session, match)]


@router.post("/bracket/matches/{match_id}/words/{game_number}", response_model=PlayoffWordQueueEntry)
async def set_bracket_word(
    match_id: int, game_number: int, payload: SetPlayoffWordRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    if not 1 <= game_number <= bracket_game.WORD_QUEUE_SIZE:
        raise HTTPException(status_code=400, detail=f"Слово можно задать только для игр 1-{bracket_game.WORD_QUEUE_SIZE} этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    already_used = await crud.get_all_used_words(session, match.tournament_id)
    already_used = already_used | await bracket_game.sibling_queue_words(session, match, game_number)
    error = validate_manual_word(payload.word, already_used)
    if error:
        raise HTTPException(status_code=400, detail=error)
    word = canonical_word(payload.word) or payload.word.strip().lower()

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None:
        if not bracket_game.game_word_editable(existing, match):
            raise HTTPException(status_code=400, detail="Игра уже началась (есть догадки) или закончилась — слово менять поздно")
        await crud.set_playoff_game_word(session, existing, word)
    else:
        await crud.set_playoff_word_override(session, match, game_number, word)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))


@router.post("/bracket/matches/{match_id}/words/{game_number}/length", response_model=PlayoffWordQueueEntry)
async def set_bracket_slot_length(
    match_id: int, game_number: int, payload: SlotLengthRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Сменить длину слова слота пары: система подбирает новое слово нужной длины
    (как «Предложить другое», но с выбранной длиной)."""
    if payload.length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина слова должна быть 5, 6 или 7 букв")
    if not 1 <= game_number <= bracket_game.WORD_QUEUE_SIZE:
        raise HTTPException(status_code=400, detail=f"Слово можно задать только для игр 1-{bracket_game.WORD_QUEUE_SIZE} этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None and not bracket_game.game_word_editable(existing, match):
        raise HTTPException(status_code=400, detail="Игра уже началась (есть догадки) или закончилась — слово менять поздно")

    await bracket_game.reroll_word_queue_slot(session, match, game_number, length=payload.length)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))


@router.post("/bracket/matches/{match_id}/words/{game_number}/reroll", response_model=PlayoffWordQueueEntry)
async def reroll_bracket_word(
    match_id: int, game_number: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """"Предложить другое слово" для пары сетки — то же, что реролл обычного
    слова дня, только для слота очереди (см. пункт бэклога)."""
    if not 1 <= game_number <= bracket_game.WORD_QUEUE_SIZE:
        raise HTTPException(status_code=400, detail=f"Слово можно задать только для игр 1-{bracket_game.WORD_QUEUE_SIZE} этой пары")
    match = await session.get(PlayoffMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Пара не найдена")

    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    if existing is not None and not bracket_game.game_word_editable(existing, match):
        raise HTTPException(status_code=400, detail="Игра уже началась (есть догадки) или закончилась — слово менять поздно")

    await bracket_game.reroll_word_queue_slot(session, match, game_number)

    queue = await bracket_game.get_word_queue(session, match)
    return PlayoffWordQueueEntry(**next(q for q in queue if q["game_number"] == game_number))
