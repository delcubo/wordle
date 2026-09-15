"""
Эндпоинты игровой части сайта. Идентификация — по персональному access_token
пользователя (глобальному, не привязанному к одному розыгрышу). Так как один
человек может участвовать в нескольких розыгрышах одновременно, для игры и
статуса дополнительно указывается tournament_id.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.schemas import TodayWordStatus, GuessRequest, GuessResponse, LetterState, MyTournamentOut, BracketTodayStatus, ThemeOut
from api.wordle_logic import check_guess, is_solved
from api.scoring import calculate_points
from api.dictionary import is_valid_word
from api.tournament_time import today, day_number_for_date, next_publish_at
from api.models import TournamentType, TournamentStatus, PlayoffMatchStatus
from api.tournament_title import render_tournament_title
from api import crud, tiebreak, bracket_game

router = APIRouter(prefix="/game", tags=["game"])

MAX_ATTEMPTS = 6


@router.get("/theme", response_model=ThemeOut)
async def get_theme(session: AsyncSession = Depends(get_session)):
    """Публичная (без токена) — тема оформления, которую задаёт админ для всех
    игроков сразу (см. пункт #9 бэклога)."""
    settings = await crud.get_app_settings(session)
    return ThemeOut(theme=settings.theme)


async def _authenticate_user(session: AsyncSession, token: str):
    user = await crud.get_user_by_token(session, token)
    if user is None or user.archived:
        raise HTTPException(status_code=404, detail="Ссылка недействительна")
    return user


async def _entry_bracket_round(session: AsyncSession, tournament_id: int, entry_id: int) -> int | None:
    """Номер раунда сетки, в котором сейчас (или последний раз) участвует entry —
    чтобы показывать игроку ЕГО СОБСТВЕННУЮ стадию в названии розыгрыша, а не
    самую дальнюю стадию по сетке в целом (см. render_tournament_title). Считаем
    только раунды, которые УЖЕ НАСТУПИЛИ — следующий раунд после победы создаётся
    сразу, но начинается только завтра (см. bracket_game.advance_winner), и до
    этого момента заголовок не должен перескакивать вперёд, пока сам раунд ещё
    недоступен (см. bracket_game.get_player_view — та же логика выбора "текущего"
    матча, оба места должны совпадать)."""
    matches = await crud.list_playoff_matches_for_entry(session, tournament_id, entry_id)
    started = [m for m in matches if (m.scheduled_date or today()) <= today()]
    if not started:
        return None
    return max(m.round_number for m in started)


async def _entry_round_number(session: AsyncSession, tournament, entry_id: int) -> int | None:
    """round_number для render_tournament_title — для tiebreak это номер дня
    активного раунда участника (см. api/tiebreak.py), для остальных типов —
    его собственная стадия сетки (см. _entry_bracket_round). None, если у
    участника сейчас нет ни активного раунда, ни начавшейся пары сетки."""
    if tournament.type == TournamentType.tiebreak:
        round_ = await crud.get_active_tiebreak_round_for_entry(session, tournament.id, entry_id)
        if round_ is None:
            return None
        daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
        return daily_word.day_number if daily_word else None
    return await _entry_bracket_round(session, tournament.id, entry_id)


@router.get("/my-tournaments", response_model=list[MyTournamentOut])
async def my_tournaments(token: str, session: AsyncSession = Depends(get_session)):
    """Список розыгрышей, в которых участвует владелец ссылки — экран 'мои розыгрыши'."""
    user = await _authenticate_user(session, token)
    entries = await crud.list_entries_for_user(session, user.id)

    result = []
    for entry in entries:
        tournament = await crud.get_tournament(session, entry.tournament_id)
        if tournament is None or tournament.paused:
            continue
        # round_number — как и в get_bracket_today/get_today_status: собственная
        # (уже наступившая) стадия ИМЕННО ЭТОГО участника, а не самая дальняя по
        # сетке в целом — иначе в списке розыгрышей могла показаться стадия,
        # которая для этого игрока ещё не началась (см. пункт бэклога).
        round_number = await _entry_round_number(session, tournament, entry.id)
        result.append(
            MyTournamentOut(
                tournament_id=tournament.id,
                title=await render_tournament_title(session, tournament, round_number),
                type=tournament.type,
                callsign=entry.callsign,
                status=tournament.status,
            )
        )
    return result


async def _resolve_context(session: AsyncSession, token: str, tournament_id: int):
    """
    Находит пользователя, его участие (entry) в указанном розыгрыше и слово на
    сегодняшний день этого розыгрыша. daily_word может быть None, если розыгрыш
    ещё не начался/уже закончился, или тип розыгрыша не подразумевает
    ежедневное слово вне пары (knockout — вне текущей реализации плей-офф).
    endless не имеет duration_days, но, в отличие от knockout, слово дня у него
    есть всегда, без верхней границы. Пока розыгрыш в статусе tiebreak, слово
    дня заменяется словом активного раунда тай-брейка (если участник в него
    попал) — обычный цикл по duration_days в этот момент уже закончился. Тип
    розыгрыша tiebreak (целиком, не только фаза championship) вообще не
    использует duration_days — там всегда только раунды, с самого начала.
    """
    user = await _authenticate_user(session, token)
    entry = await crud.get_entry(session, tournament_id, user.id)
    if entry is None:
        raise HTTPException(status_code=403, detail="Вы не участвуете в этом розыгрыше")

    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")

    if tournament.paused:
        # Немедленная деактивация админом — блокирует игру для всех участников
        # независимо от фазы, до тех пор пока не будет включена обратно.
        return entry, tournament, None

    if tournament.type == TournamentType.knockout:
        # у knockout нет слова дня вне сетки вообще — играют только через
        # /game/bracket/today и /game/bracket/guess, с первого дня
        return entry, tournament, None

    if tournament.type == TournamentType.tiebreak:
        # весь розыгрыш — раунды тай-брейка с самого начала (см. api/tiebreak.py),
        # обычного слова дня по duration_days тут вообще не бывает
        await tiebreak.ensure_started(session, tournament)
        round_ = await crud.get_active_tiebreak_round_for_entry(session, tournament.id, entry.id)
        if round_ is None:
            return entry, tournament, None  # ещё не стартовал / ждёт итогов раунда / уже получил место
        daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
        return entry, tournament, daily_word

    if tournament.status == TournamentStatus.tiebreak:
        round_ = await crud.get_active_tiebreak_round_for_entry(session, tournament.id, entry.id)
        if round_ is None:
            return entry, tournament, None  # не в тай-брейк-группе — просто ждёт итогов
        daily_word = await crud.get_daily_word_by_id(session, round_.daily_word_id)
        return entry, tournament, daily_word

    day_number = day_number_for_date(tournament.start_date, today())
    if day_number < 1:
        return entry, tournament, None
    if tournament.duration_days is not None and day_number > tournament.duration_days:
        return entry, tournament, None

    daily_word = await crud.get_or_suggest_daily_word(session, tournament, day_number)
    return entry, tournament, daily_word


@router.get("/today", response_model=TodayWordStatus)
async def get_today_status(token: str, tournament_id: int, session: AsyncSession = Depends(get_session)):
    entry, tournament, daily_word = await _resolve_context(session, token, tournament_id)
    round_number = await _entry_round_number(session, tournament, entry.id)
    tournament_title = await render_tournament_title(session, tournament, round_number)
    is_endless = tournament.type == TournamentType.endless
    is_tiebreak = tournament.type == TournamentType.tiebreak
    # Тот же формат отчёта, что и у endless (см. ResultModal), но со звездой
    # вместо ▪️ — для standard/championship, и только пока идёт таблица
    # основного этапа (до тай-брейка/плей-офф, см. пункт бэклога).
    is_standard_report = (
        tournament.type in (TournamentType.standard, TournamentType.championship)
        and tournament.status not in (TournamentStatus.tiebreak, TournamentStatus.playoff)
    )

    tiebreak_started = False
    tiebreak_place = None
    if is_tiebreak:
        tiebreak_started = bool(await crud.list_root_tiebreak_rounds(session, tournament.id))
        if tiebreak_started:
            tiebreak_place = await tiebreak.get_entry_place(session, tournament, entry.id)

    if daily_word is None:
        return TodayWordStatus(
            has_word_today=False, already_played=False, callsign=entry.callsign, tournament_title=tournament_title,
            base_title=tournament.title, is_endless=is_endless, hashtag=tournament.hashtag, paused=tournament.paused,
            is_tiebreak=is_tiebreak, tiebreak_started=tiebreak_started, tiebreak_place=tiebreak_place,
            is_standard_report=is_standard_report,
        )

    attempt = await crud.get_attempt(session, entry.id, daily_word.id)
    if attempt is None:
        return TodayWordStatus(
            has_word_today=True, already_played=False, day_number=daily_word.day_number, max_attempts=MAX_ATTEMPTS,
            callsign=entry.callsign, tournament_title=tournament_title, base_title=tournament.title,
            is_endless=is_endless, hashtag=tournament.hashtag,
            is_tiebreak=is_tiebreak, tiebreak_started=tiebreak_started, tiebreak_place=tiebreak_place,
            is_standard_report=is_standard_report,
        )

    already_played = attempt.solved or attempt.attempts_used >= MAX_ATTEMPTS
    streak_days = None
    if already_played and is_standard_report:
        streak_days = await crud.compute_played_streak(session, tournament.id, entry.id, daily_word.day_number)
    # Раскраску прошлых попыток и (при поражении) сам ответ отдаём всегда, когда
    # есть попытка — не только по завершении: иначе при возврате в недоигранную
    # игру клиент не может восстановить ни цвета, ни номер текущей строки.
    return TodayWordStatus(
        has_word_today=True,
        already_played=already_played,
        day_number=daily_word.day_number,
        attempts_used=attempt.attempts_used,
        solved=attempt.solved,
        previous_guesses=attempt.guesses,
        previous_results=[check_guess(g, daily_word.word) for g in attempt.guesses],
        answer_word=daily_word.word if already_played and not attempt.solved else None,
        max_attempts=MAX_ATTEMPTS,
        callsign=entry.callsign,
        tournament_title=tournament_title,
        base_title=tournament.title,
        is_endless=is_endless,
        hashtag=tournament.hashtag,
        next_word_at=next_publish_at().isoformat() if already_played and not is_tiebreak else None,
        is_tiebreak=is_tiebreak, tiebreak_started=tiebreak_started, tiebreak_place=tiebreak_place,
        is_standard_report=is_standard_report, streak_days=streak_days,
    )


@router.post("/guess", response_model=GuessResponse)
async def submit_guess(payload: GuessRequest, session: AsyncSession = Depends(get_session)):
    guess = payload.guess.strip().lower()

    if len(guess) != 5:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5 букв")
    if not is_valid_word(guess):
        raise HTTPException(status_code=400, detail="Такого слова нет в словаре")

    entry, tournament, daily_word = await _resolve_context(session, payload.token, payload.tournament_id)
    if daily_word is None:
        raise HTTPException(status_code=400, detail="Слово дня сегодня недоступно")

    # Состояние попытки хранится на сервере и привязано к entry.id — открытие той же
    # персональной ссылки с другого устройства не даёт мошеннически начать заново.
    attempt = await crud.get_or_create_attempt(session, entry.id, daily_word.id)

    if attempt.solved or attempt.attempts_used >= MAX_ATTEMPTS:
        raise HTTPException(status_code=400, detail="Попытки на сегодня исчерпаны")

    statuses = check_guess(guess, daily_word.word)
    solved = is_solved(statuses)
    attempts_used = attempt.attempts_used + 1
    game_over = solved or attempts_used >= MAX_ATTEMPTS

    points = None
    if game_over and tournament.scoring_rules is not None:
        points = calculate_points(attempts_used, solved, tournament.scoring_rules)

    await crud.save_guess(session, attempt, guess, solved, game_over, points)

    if game_over and (tournament.status == TournamentStatus.tiebreak or tournament.type == TournamentType.tiebreak):
        # как только все участники раунда доиграли — сразу разрешаем его, не дожидаясь
        # дедлайна, чтобы продолжение (при остаточной ничьей) стало доступно тут же
        await tiebreak.resolve_ready_rounds(session, tournament)

    return GuessResponse(
        result=[LetterState(letter=g, state=s) for g, s in zip(guess, statuses)],
        solved=solved,
        attempts_used=attempts_used,
        attempts_remaining=MAX_ATTEMPTS - attempts_used,
        game_over=game_over,
        points=points,
    )


# ---------- Сетка плей-офф (championship после посева, knockout всегда) ----------

@router.get("/bracket/today", response_model=BracketTodayStatus)
async def get_bracket_today(token: str, tournament_id: int, session: AsyncSession = Depends(get_session)):
    user = await _authenticate_user(session, token)
    entry = await crud.get_entry(session, tournament_id, user.id)
    if entry is None:
        raise HTTPException(status_code=403, detail="Вы не участвуете в этом розыгрыше")
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")

    round_number = await _entry_bracket_round(session, tournament_id, entry.id)
    tournament_title = await render_tournament_title(session, tournament, round_number)
    if tournament.paused:
        return BracketTodayStatus(
            has_match=False, callsign=entry.callsign, tournament_title=tournament_title,
            hashtag=tournament.hashtag, paused=True,
        )

    # тот же лениво-вычисляемый паттерн, что и у слова дня/тай-брейка: пары,
    # чей дедлайн уже прошёл, разрешаются прямо при заходе игрока
    await bracket_game.resolve_ready_matches(session, tournament)

    view = await bracket_game.get_player_view(session, tournament, entry)
    # Отсчёт до следующего слова показываем только тем, для кого действительно
    # есть следующее слово: победителю пары (следующий раунд — завтра) или
    # игроку, доигравшему обычный день/тай-брейк. Проигравшему пару — нет,
    # для него розыгрыш на этом закончен (см. ResultModal: "игра окончена").
    next_word_at = None
    if view.get("match_finished") and view.get("won"):
        next_word_at = next_publish_at().isoformat()
    return BracketTodayStatus(
        **view, callsign=entry.callsign, tournament_title=tournament_title, hashtag=tournament.hashtag,
        next_word_at=next_word_at,
    )


@router.post("/bracket/guess", response_model=GuessResponse)
async def submit_bracket_guess(payload: GuessRequest, session: AsyncSession = Depends(get_session)):
    guess = payload.guess.strip().lower()

    if len(guess) != 5:
        raise HTTPException(status_code=400, detail="Слово должно быть из 5 букв")
    if not is_valid_word(guess):
        raise HTTPException(status_code=400, detail="Такого слова нет в словаре")

    user = await _authenticate_user(session, payload.token)
    entry = await crud.get_entry(session, payload.tournament_id, user.id)
    if entry is None:
        raise HTTPException(status_code=403, detail="Вы не участвуете в этом розыгрыше")
    tournament = await crud.get_tournament(session, payload.tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.paused:
        raise HTTPException(status_code=400, detail="Розыгрыш временно приостановлен")

    matches = await crud.list_playoff_matches_for_entry(session, tournament.id, entry.id)
    active_matches = [m for m in matches if m.status != PlayoffMatchStatus.finished]
    if not active_matches:
        raise HTTPException(status_code=400, detail="У вас сейчас нет активного матча сетки")

    try:
        statuses, solved, attempts_used, game_over = await bracket_game.submit_guess(
            session, tournament, active_matches[0], entry.id, guess
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return GuessResponse(
        result=[LetterState(letter=g, state=s) for g, s in zip(guess, statuses)],
        solved=solved,
        attempts_used=attempts_used,
        attempts_remaining=MAX_ATTEMPTS - attempts_used,
        game_over=game_over,
        points=None,
    )
