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
    UserCreateRequest, UserOut, UserEditRequest,
    TournamentConfigRequest, TournamentOut,
    EntryCreateRequest, EntryOut, EntryEditRequest,
    DailyWordOut, ConfirmWordRequest,
    StandingsResponse, StandingsRowOut, DailyCell,
)
from api.models import Tournament, TournamentStatus, TournamentType, User, TournamentEntry
from api.admin_auth import check_password, create_session_token, require_admin, COOKIE_NAME
from api.dictionary import validate_manual_word
from api.tournament_time import today, day_number_for_date
from api import crud
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


# ---------- Users (глобальный список игроков) ----------

@router.post("/users", response_model=UserOut)
async def create_user(payload: UserCreateRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    user = await crud.create_user(session, payload.admin_note)
    return UserOut(id=user.id, access_token=user.access_token, admin_note=user.admin_note, created_at=str(user.created_at))


@router.get("/users", response_model=list[UserOut])
async def get_users(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    users = await crud.list_users(session)
    return [UserOut(id=u.id, access_token=u.access_token, admin_note=u.admin_note, created_at=str(u.created_at)) for u in users]


@router.patch("/users/{user_id}", response_model=UserOut)
async def edit_user(user_id: int, payload: UserEditRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    user = await crud.edit_user_note(session, user_id, payload.admin_note)
    if user is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    return UserOut(id=user.id, access_token=user.access_token, admin_note=user.admin_note, created_at=str(user.created_at))


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
        status=TournamentStatus.draft,
    )
    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    return tournament


@router.get("/tournaments", response_model=list[TournamentOut])
async def get_tournaments(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await crud.list_tournaments(session)


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
    if await crud.get_entry(session, tournament_id, payload.user_id) is not None:
        raise HTTPException(status_code=400, detail="Этот игрок уже подключён к розыгрышу")
    if await crud.callsign_taken(session, tournament_id, payload.callsign):
        raise HTTPException(status_code=400, detail="Этот позывной уже занят в текущем розыгрыше")

    entry = await crud.create_entry(session, tournament, payload.user_id, payload.callsign)
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


# ---------- Подтверждение слова дня ----------

@router.get("/tournaments/{tournament_id}/words", response_model=list[DailyWordOut])
async def get_words(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return await crud.list_daily_words(session, tournament_id)


@router.get("/tournaments/{tournament_id}/words/upcoming", response_model=DailyWordOut)
async def get_upcoming_word(tournament_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """
    Слово на ближайший ещё не наступивший день — то, что админ может подтвердить
    или заменить. Если розыгрыш уже полностью прошёл или сегодняшний день ещё не
    сыгран, возвращает соответствующую ошибку.
    """
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None or tournament.duration_days is None:
        raise HTTPException(status_code=400, detail="У этого розыгрыша нет ежедневного слова")

    current_day = day_number_for_date(tournament.start_date, today())
    next_day = max(current_day, 0) + 1  # ближайший день, который ещё не наступил
    if next_day > tournament.duration_days:
        raise HTTPException(status_code=400, detail="Розыгрыш уже завершается — новых дней не осталось")

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, next_day)
    return daily_word


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
        override = payload.override_word.strip().lower()
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
                daily=[DailyCell(played=d.played, points=d.points) for d in r.daily],
            )
            for r in rows
        ],
        total_days=tournament.duration_days,
        skip_flag_symbol=tournament.skip_flag_symbol,
    )
