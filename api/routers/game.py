"""
Эндпоинты игровой части сайта. Идентификация — по персональному access_token
пользователя (глобальному, не привязанному к одному розыгрышу). Так как один
человек может участвовать в нескольких розыгрышах одновременно, для игры и
статуса дополнительно указывается tournament_id.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.schemas import (
    TodayWordStatus, GuessRequest, GuessResponse, LetterState, MyTournamentOut, BracketTodayStatus, ThemeOut,
    BonusStateOut, BonusTodayStatus, BonusGuessRequest,
)
from api.wordle_logic import check_guess, is_solved
from api.scoring import calculate_points
from api.dictionary import is_valid_word
from api.tournament_time import today, day_number_for_date, next_publish_at, effective_status, TOURNAMENT_TZ
from api.models import TournamentType, TournamentStatus, PlayoffMatchStatus
from api.tournament_title import render_tournament_title, THIRD_PLACE_STAGE
from api import crud, tiebreak, bracket_game, notify, marathon, bonus
from api.report import build_report_text, build_marathon_summary_text
from api import teams
from api.word_plan import base_length

logger = logging.getLogger("wordle.game")

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
    current = max(started, key=lambda m: m.round_number)
    return THIRD_PLACE_STAGE if current.is_third_place else current.round_number


async def _entry_round_number(session: AsyncSession, tournament, entry_id: int) -> int | None:
    """round_number для render_tournament_title — для tiebreak это номер дня
    активного раунда участника (см. api/tiebreak.py), для остальных типов —
    его собственная стадия сетки (см. _entry_bracket_round). None, если у
    участника сейчас нет ни активного раунда, ни начавшейся пары сетки."""
    if tournament.type == TournamentType.tiebreak:
        round_ = await crud.get_active_tiebreak_round_for_entry(session, tournament.id, entry_id)
        # round_.round_number — настоящая глубина в цепочке тай-брейка (1, 2, 3...).
        # НЕ day_number связанного DailyWord: та нумерация сквозная по всему
        # розыгрышу (см. crud.py::_next_free_day_number) и у параллельных
        # подгрупп одного и того же уровня (см. tiebreak.py::_try_resolve_round)
        # отличается, потому что слова для них заводятся по очереди — иначе
        # игрокам из разных подгрупп одного раунда показывались бы разные номера.
        return round_.round_number if round_ else None
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
        bonus_fields = await _bonus_fields(session, tournament, entry)
        result.append(
            MyTournamentOut(
                tournament_id=tournament.id,
                title=await render_tournament_title(session, tournament, round_number),
                type=tournament.type,
                callsign=entry.callsign,
                status=effective_status(tournament),
                bonus_available=bonus_fields.get("bonus_open_number") is not None,
            )
        )
    return result


def _unavailable_info(tournament, day_number: int | None = None) -> dict:
    """
    Почему у игрока нет слова на сегодня: розыгрыш ещё не начался или уже
    завершён — чтобы на фронте показать разные тексты вместо общего. Возвращает
    поля для TodayWordStatus/BracketTodayStatus; пустой словарь, если причина
    не определена (например, championship между этапами).
    """
    if today() < tournament.start_date:
        return {"unavailable_reason": "not_started", "start_date": tournament.start_date.isoformat()}
    if tournament.status == TournamentStatus.finished:
        return {"unavailable_reason": "finished"}
    if tournament.type == TournamentType.marathon and marathon.has_ended(tournament):
        return {"unavailable_reason": "finished"}
    if (
        tournament.type == TournamentType.standard and tournament.duration_days is not None
        and day_number is not None and day_number > tournament.duration_days
    ):
        return {"unavailable_reason": "finished"}
    return {}


async def _daily_report_text(session: AsyncSession, tournament, entry, daily_word, attempt, tournament_title: str) -> str:
    """
    Готовый текст отчёта об игре со словом дня (стандартный, бессрочный,
    тай-брейк) — тот же, что игрок копирует из попапа; его же получает админ в
    уведомлении (см. api/report.py, api/notify.py).
    """
    is_tiebreak = tournament.type == TournamentType.tiebreak
    is_endless = tournament.type == TournamentType.endless
    is_standard_report = (
        tournament.type in (TournamentType.standard, TournamentType.championship)
        and tournament.status not in (TournamentStatus.tiebreak, TournamentStatus.playoff)
    )
    kind = "tiebreak" if is_tiebreak else "endless" if is_endless else "standard" if is_standard_report else None

    day_number = daily_word.day_number
    if is_tiebreak:
        # для тай-брейка в отчёте — номер раунда в цепочке, а не сквозной номер дня слова
        round_ = await crud.get_tiebreak_round_by_daily_word(session, daily_word.id)
        day_number = round_.round_number if round_ else None

    streak_days = None
    if kind == "standard" and (attempt.solved or attempt.attempts_used >= MAX_ATTEMPTS):
        streak_days = await crud.compute_played_streak(session, tournament.id, entry.id, daily_word.day_number)

    return build_report_text(
        kind=kind,
        attempts_used=attempt.attempts_used,
        solved=attempt.solved,
        grid=[check_guess(g, daily_word.word) for g in attempt.guesses],
        callsign=entry.callsign,
        hashtag=tournament.hashtag,
        base_title=tournament.title,
        day_number=day_number,
        streak_days=streak_days,
        title=tournament_title,
        team_name=await teams.team_name_for_entry(session, tournament, entry) if is_tiebreak else None,
    )


async def _bracket_stage_label(session: AsyncSession, tournament, entry, tournament_title: str | None = None) -> str | None:
    """Метка стадии сетки ("1/4 финала") — хвост заголовка "<название> <стадия>"
    (см. render_tournament_title)."""
    if tournament_title is None:
        round_number = await _entry_bracket_round(session, tournament.id, entry.id)
        tournament_title = await render_tournament_title(session, tournament, round_number)
    if tournament_title.startswith(tournament.title + " "):
        return tournament_title[len(tournament.title) + 1:]
    return None


def _bracket_report_text(tournament, entry, view: dict, stage_label: str | None) -> str:
    # пара из нескольких игр: в отчёте видно, какая это игра («игра 2/3»; дополнительная — «доп. игра»)
    if view.get("is_sudden_death"):
        stage_label = f"{stage_label} · доп. игра" if stage_label else "доп. игра"
    elif (view.get("games_required") or 1) > 1:
        suffix = f"игра {view['game_number']}/{view['games_required']}"
        stage_label = f"{stage_label} · {suffix}" if stage_label else suffix
    return build_report_text(
        kind="bracket",
        attempts_used=view["attempts_used"],
        solved=bool(view["solved"]),
        grid=view["previous_results"],
        callsign=entry.callsign,
        hashtag=tournament.hashtag,
        base_title=tournament.title,
        stage_label=stage_label,
    )


def _notification_footer(finished_at, played: int | None, total: int | None) -> str:
    """Строка под отчётом в уведомлении админу: время окончания и "сыграло N/M" —
    сколько участников уже закончили партию из всех, кто играет на этой стадии."""
    local = finished_at.replace(tzinfo=timezone.utc).astimezone(TOURNAMENT_TZ)
    tz_label = {"MSK": "МСК"}.get(local.tzname(), local.tzname())
    parts = [f"\U0001f552 {local.strftime('%H:%M')} {tz_label}"]
    if played is not None and total:
        parts.append(f"сыграло {played}/{total}")
    return " · ".join(parts)


async def _notify_daily_finished(session: AsyncSession, tournament, entry, daily_word, attempt) -> None:
    """Уведомление админу о законченной партии со словом дня. Что бы ни
    случилось, игре это не мешает (см. api/notify.py)."""
    if tournament.type == TournamentType.marathon:
        return  # у марафона своё уведомление — когда пройдены все слова
    if not tournament.notify_admin or not notify.is_configured():
        return
    try:
        round_number = await _entry_round_number(session, tournament, entry.id)
        title = await render_tournament_title(session, tournament, round_number)
        text = await _daily_report_text(session, tournament, entry, daily_word, attempt, title)
        # M: у тай-брейка — участники именно этого раунда, иначе — подключённые
        # к розыгрышу (активные) участники; N считается среди них же
        if tournament.type == TournamentType.tiebreak:
            round_ = await crud.get_tiebreak_round_by_daily_word(session, daily_word.id)
            ids = {p.entry_id for p in await crud.list_tiebreak_participants(session, round_.id)} if round_ else set()
            played = (
                await crud.count_round_finished_until(session, round_, attempt.finished_at) if round_ else 0
            )  # в командном тай-брейке у каждого своё слово
        else:
            ids = {e.id for e in await crud.list_entries(session, tournament.id) if e.active}
            played = await crud.count_finished_attempts_until(session, daily_word.id, attempt.finished_at, ids)
        footer = _notification_footer(attempt.finished_at, played, len(ids))
        notify.notify_admin_in_background(f"{text}\n\n{footer}")
    except Exception:
        logger.exception("Не удалось подготовить уведомление админу")


async def _notify_bracket_finished(session: AsyncSession, tournament, entry, game_number: int | None = None) -> None:
    if not tournament.notify_admin or not notify.is_configured():
        return
    try:
        view = await bracket_game.get_player_view(session, tournament, entry, game_number)
        if not view.get("has_match") or view.get("attempts_used") is None:
            return
        stage_label = await _bracket_stage_label(session, tournament, entry)
        text = _bracket_report_text(tournament, entry, view, stage_label)
        played, total = await crud.count_bracket_stage_progress(
            session, tournament.id, view["round_number"], third_place=bool(view.get("is_third_place"))
        )
        notify.notify_admin_in_background(f"{text}\n\n{_notification_footer(datetime.utcnow(), played, total)}")
    except Exception:
        logger.exception("Не удалось подготовить уведомление админу (сетка)")


def _marathon_final_text(tournament, entry, progress, team_name: str | None = None) -> str:
    """Итоговый отчёт марафона — когда пройдены все слова."""
    return build_marathon_summary_text(
        base_title=tournament.title, callsign=entry.callsign, hashtag=tournament.hashtag, team_name=team_name,
        results=[(a.attempts_used, bool(a.solved)) for _, a in progress.finished],
        total_attempts=progress.total_attempts, unsolved_attempts=marathon.UNSOLVED_ATTEMPTS,
    )


async def _notify_marathon_finished(session: AsyncSession, tournament, entry, text: str) -> None:
    """Админу — одно сообщение, когда игрок прошёл ВСЕ слова марафона."""
    if not tournament.notify_admin or not notify.is_configured():
        return
    try:
        standings = await marathon.compute_standings(session, tournament)
        played = sum(1 for r in standings["rows"] if r["finished_all"])
        total = len([e for e in await crud.list_entries(session, tournament.id) if e.active and not e.hidden_from_standings])
        notify.notify_admin_in_background(f"{text}\n\n{_notification_footer(datetime.utcnow(), played, total)}")
    except Exception:
        logger.exception("Не удалось подготовить уведомление админу (марафон)")


async def _marathon_after_word(session: AsyncSession, tournament, entry, daily_word, attempt) -> dict:
    """Поля ответа на последнюю догадку слова марафона: ответ, отчёт, есть ли дальше."""
    progress = await marathon.get_progress(session, tournament, entry.id)
    team_name = await teams.team_name_for_entry(session, tournament, entry)
    if progress.done:
        text = _marathon_final_text(tournament, entry, progress, team_name)
        await _notify_marathon_finished(session, tournament, entry, text)
    else:
        text = build_report_text(
            kind="marathon", attempts_used=attempt.attempts_used, solved=attempt.solved,
            grid=[check_guess(g, daily_word.word) for g in attempt.guesses], callsign=entry.callsign,
            hashtag=tournament.hashtag, base_title=tournament.title, team_name=team_name,
            stage_label=f"слово {daily_word.day_number}/{progress.total}",
        )
    return dict(
        answer_word=None if attempt.solved else daily_word.word, report_text=text,
        has_next_word=not progress.done, word_index=daily_word.day_number, words_total=progress.total,
        marathon_total_attempts=progress.total_attempts if progress.done else None,
    )


async def _marathon_status(session: AsyncSession, tournament, entry) -> TodayWordStatus:
    """Статус игрока в марафоне: текущее слово (с уже введёнными попытками), либо
    «все слова пройдены», либо игра недоступна (не началась / закрыта / пауза)."""
    base = dict(
        callsign=entry.callsign, tournament_title=tournament.title, base_title=tournament.title,
        hashtag=tournament.hashtag, paused=tournament.paused, is_marathon=True, max_attempts=MAX_ATTEMPTS,
    )
    if tournament.paused:
        return TodayWordStatus(has_word_today=False, already_played=False, word_length=base_length(tournament), **base)
    if not marathon.is_open(tournament):
        return TodayWordStatus(
            has_word_today=False, already_played=False, word_length=base_length(tournament),
            **base, **_unavailable_info(tournament),
        )

    progress = await marathon.get_progress(session, tournament, entry.id)
    if progress.done:
        return TodayWordStatus(
            has_word_today=False, already_played=False, marathon_done=True, word_index=progress.total,
            word_length=base_length(tournament),
            words_total=progress.total, marathon_total_attempts=progress.total_attempts,
            report_text=_marathon_final_text(
                tournament, entry, progress, await teams.team_name_for_entry(session, tournament, entry)
            ), **base,
        )

    daily_word = progress.current
    attempt = progress.attempts.get(daily_word.day_number)
    common = dict(
        has_word_today=True, already_played=False, day_number=daily_word.day_number,
        word_index=daily_word.day_number, words_total=progress.total, word_length=len(daily_word.word), **base,
    )
    if attempt is None:
        return TodayWordStatus(**common)
    return TodayWordStatus(
        attempts_used=attempt.attempts_used, solved=attempt.solved, previous_guesses=attempt.guesses,
        previous_results=[check_guess(g, daily_word.word) for g in attempt.guesses], **common,
    )


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

    if tournament.type == TournamentType.marathon:
        # слова идут по порядку для каждого игрока отдельно: текущее — первое,
        # которое он ещё не закончил (см. api/marathon.py); None — игра закрыта
        # по датам либо все слова уже пройдены
        if not marathon.is_open(tournament):
            return entry, tournament, None
        progress = await marathon.get_progress(session, tournament, entry.id)
        return entry, tournament, progress.current

    if tournament.type == TournamentType.tiebreak:
        # весь розыгрыш — раунды тай-брейка с самого начала (см. api/tiebreak.py),
        # обычного слова дня по duration_days тут вообще не бывает
        await tiebreak.ensure_started(session, tournament)
        round_ = await crud.get_active_tiebreak_round_for_entry(session, tournament.id, entry.id)
        if round_ is None:
            return entry, tournament, None  # ещё не стартовал / ждёт итогов раунда / уже получил место
        daily_word = await tiebreak.word_for_entry(session, round_, entry.id)  # в командном — своё слово
        return entry, tournament, daily_word

    if tournament.status == TournamentStatus.tiebreak:
        round_ = await crud.get_active_tiebreak_round_for_entry(session, tournament.id, entry.id)
        if round_ is None:
            return entry, tournament, None  # не в тай-брейк-группе — просто ждёт итогов
        daily_word = await tiebreak.word_for_entry(session, round_, entry.id)
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
    if tournament.type == TournamentType.marathon:
        return await _marathon_status(session, tournament, entry)
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

    team_name = await teams.team_name_for_entry(session, tournament, entry) if is_tiebreak else None
    bonus_fields = await _bonus_fields(session, tournament, entry)
    tiebreak_started = False
    tiebreak_place = None
    if is_tiebreak:
        tiebreak_started = bool(await crud.list_root_tiebreak_rounds(session, tournament.id))
        if tiebreak_started:
            tiebreak_place = await tiebreak.get_entry_place(session, tournament, entry.id)

    # логика ниже идёт по относительному месту, игроку показываем со сдвигом на
    # первое разыгрываемое место (см. tiebreak.shift_place)
    shown_tiebreak_place = tiebreak.shift_place(tiebreak_place, tournament.first_place)

    if daily_word is None:
        # Тай-брейк уже закончился лично для этого участника (место не диапазон,
        # а точное число — см. tiebreak.get_entry_place) — вместо пустого поля
        # ввода отдаём сетку его последней сыгранной попытки, как при обычном
        # завершённом дне, чтобы фронт показал попап, а не голую доску (см.
        # пункт бэклога).
        last_attempt_fields = {}
        if is_tiebreak and tiebreak_place is not None and "-" not in tiebreak_place:
            last_round = await crud.get_last_tiebreak_round_for_entry(session, tournament.id, entry.id)
            last_word_id = await crud.round_word_id_for_entry(session, last_round, entry.id) if last_round else None
            last_attempt = await crud.get_attempt(session, entry.id, last_word_id) if last_word_id else None
            if last_attempt is not None:
                last_daily_word = await crud.get_daily_word_by_id(session, last_word_id)
                last_attempt_fields = dict(
                    report_text=await _daily_report_text(
                        session, tournament, entry, last_daily_word, last_attempt, tournament_title
                    ),
                    day_number=last_round.round_number,
                    attempts_used=last_attempt.attempts_used,
                    solved=last_attempt.solved,
                    previous_guesses=last_attempt.guesses,
                    previous_results=[check_guess(g, last_daily_word.word) for g in last_attempt.guesses],
                    answer_word=last_daily_word.word if not last_attempt.solved else None,
                )
        return TodayWordStatus(
            has_word_today=False, already_played=False, callsign=entry.callsign, tournament_title=tournament_title,
            base_title=tournament.title, is_endless=is_endless, hashtag=tournament.hashtag, paused=tournament.paused,
            is_tiebreak=is_tiebreak, tiebreak_started=tiebreak_started, tiebreak_place=shown_tiebreak_place,
            team_name=team_name, is_standard_report=is_standard_report, word_length=base_length(tournament),
            **last_attempt_fields, **bonus_fields,
            **(
                _unavailable_info(tournament, day_number_for_date(tournament.start_date, today()))
                if not is_tiebreak and not tournament.paused and tournament.status not in (TournamentStatus.tiebreak, TournamentStatus.playoff) else {}
            ),
        )

    # Для tiebreak day_number отчёта/заголовка — номер раунда в цепочке
    # (round_number, уже посчитан выше как round_number), а не сквозной
    # day_number связанного DailyWord — см. пункт бэклога (та же путаница,
    # что чинили в _entry_round_number).
    report_day_number = round_number if is_tiebreak else daily_word.day_number

    attempt = await crud.get_attempt(session, entry.id, daily_word.id)
    if attempt is None:
        return TodayWordStatus(
            has_word_today=True, already_played=False, day_number=report_day_number, max_attempts=MAX_ATTEMPTS,
            callsign=entry.callsign, tournament_title=tournament_title, base_title=tournament.title,
            is_endless=is_endless, hashtag=tournament.hashtag,
            is_tiebreak=is_tiebreak, tiebreak_started=tiebreak_started, tiebreak_place=shown_tiebreak_place,
            team_name=team_name, is_standard_report=is_standard_report, word_length=len(daily_word.word),
            **bonus_fields,
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
        day_number=report_day_number,
        attempts_used=attempt.attempts_used,
        solved=attempt.solved,
        previous_guesses=attempt.guesses,
        previous_results=[check_guess(g, daily_word.word) for g in attempt.guesses],
        answer_word=daily_word.word if already_played and not attempt.solved else None,
        report_text=(
            await _daily_report_text(session, tournament, entry, daily_word, attempt, tournament_title)
            if already_played else None
        ),
        max_attempts=MAX_ATTEMPTS,
        callsign=entry.callsign,
        tournament_title=tournament_title,
        base_title=tournament.title,
        is_endless=is_endless,
        hashtag=tournament.hashtag,
        next_word_at=next_publish_at().isoformat() if already_played and not is_tiebreak else None,
        is_tiebreak=is_tiebreak, tiebreak_started=tiebreak_started, tiebreak_place=shown_tiebreak_place,
        team_name=team_name, is_standard_report=is_standard_report, streak_days=streak_days,
        word_length=len(daily_word.word), **bonus_fields,
    )


@router.post("/guess", response_model=GuessResponse)
async def submit_guess(payload: GuessRequest, session: AsyncSession = Depends(get_session)):
    guess = payload.guess.strip().lower()

    entry, tournament, daily_word = await _resolve_context(session, payload.token, payload.tournament_id)
    if daily_word is None:
        raise HTTPException(status_code=400, detail="Слово дня сегодня недоступно")

    # длина догадки — длина текущего слова (у разных розыгрышей и позиций она своя)
    length = len(daily_word.word)
    if len(guess) != length:
        raise HTTPException(status_code=400, detail=f"Слово должно быть из {length} букв")
    if not is_valid_word(guess, length):
        raise HTTPException(status_code=400, detail="Такого слова нет в словаре")

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

    saved_attempt = await crud.save_guess(session, attempt, guess, solved, game_over, points)

    if game_over and (tournament.status == TournamentStatus.tiebreak or tournament.type == TournamentType.tiebreak):
        # как только все участники раунда доиграли — сразу разрешаем его, не дожидаясь
        # дедлайна, чтобы продолжение (при остаточной ничьей) стало доступно тут же
        await tiebreak.resolve_ready_rounds(session, tournament)

    marathon_fields = {}
    if game_over and tournament.type == TournamentType.marathon:
        marathon_fields = await _marathon_after_word(session, tournament, entry, daily_word, saved_attempt)
    elif game_over:
        await _notify_daily_finished(session, tournament, entry, daily_word, saved_attempt)

    return GuessResponse(
        result=[LetterState(letter=g, state=s) for g, s in zip(guess, statuses)],
        solved=solved,
        attempts_used=attempts_used,
        attempts_remaining=MAX_ATTEMPTS - attempts_used,
        game_over=game_over,
        points=points,
        **marathon_fields,
    )


# ---------- Бонусные слова (standard и основной этап championship, см. api/bonus.py) ----------

async def _bonus_fields(session: AsyncSession, tournament, entry) -> dict:
    """Поля статуса со сводкой бонусов игрока; пусто, если у розыгрыша бонусов нет."""
    if tournament.type not in (TournamentType.standard, TournamentType.championship) or not bonus.active_for_players(tournament):
        return {}
    states = (await bonus.compute_states(session, tournament, [entry])).get(entry.id, [])
    return dict(
        bonus=[
            BonusStateOut(
                number=s["number"], opening_day=s["opening_day"], block_start=s["block_start"], state=s["state"],
                length=s["length"], points=s["points"], attempts_used=s["attempts_used"],
            )
            for s in states
        ],
        bonus_open_number=next((s["number"] for s in states if s["state"] == "open"), None),
    )


async def _bonus_context(session: AsyncSession, token: str, tournament_id: int):
    user = await _authenticate_user(session, token)
    entry = await crud.get_entry(session, tournament_id, user.id)
    if entry is None:
        raise HTTPException(status_code=403, detail="Вы не участвуете в этом розыгрыше")
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.paused:
        raise HTTPException(status_code=400, detail="Розыгрыш временно приостановлен админом")
    if not bonus.active_for_players(tournament):
        raise HTTPException(status_code=400, detail="В этом розыгрыше нет бонусных слов")
    return entry, tournament


def _bonus_report_text(tournament, entry, number: int, attempt, word: str) -> str:
    return build_report_text(
        kind="bonus", attempts_used=attempt.attempts_used, solved=attempt.solved,
        grid=[check_guess(g, word) for g in attempt.guesses], callsign=entry.callsign, hashtag=tournament.hashtag,
        base_title=tournament.title, stage_label=f"бонус {number}",
    )


async def _bonus_state_for(session: AsyncSession, tournament, entry, number: int) -> dict:
    states = (await bonus.compute_states(session, tournament, [entry])).get(entry.id, [])
    state = next((s for s in states if s["number"] == number), None)
    if state is None:
        raise HTTPException(status_code=404, detail="Бонусного слова с таким номером нет")
    return state


@router.get("/bonus/today", response_model=BonusTodayStatus)
async def get_bonus_status(token: str, tournament_id: int, number: int, session: AsyncSession = Depends(get_session)):
    """Бонусное слово игрока: состояние, уже сделанные попытки, при завершении — результат и отчёт."""
    entry, tournament = await _bonus_context(session, token, tournament_id)
    state = await _bonus_state_for(session, tournament, entry, number)
    dw = await bonus.get_bonus_word(session, tournament.id, number)
    attempt = await crud.get_attempt(session, entry.id, dw.id) if dw is not None else None
    finished = bonus.attempt_finished(attempt)
    return BonusTodayStatus(
        number=number, state=state["state"], length=state["length"], opening_day=state["opening_day"],
        tournament_title=tournament.title, callsign=entry.callsign, hashtag=tournament.hashtag,
        attempts_used=attempt.attempts_used if attempt else 0, solved=attempt.solved if attempt else None,
        finished=finished, points=attempt.points if finished else None,
        previous_guesses=list(attempt.guesses) if attempt else [],
        previous_results=[check_guess(g, dw.word) for g in attempt.guesses] if attempt else [],
        answer_word=dw.word if finished and not attempt.solved else None,
        report_text=_bonus_report_text(tournament, entry, number, attempt, dw.word) if finished else None,
    )


@router.post("/bonus/guess", response_model=GuessResponse)
async def submit_bonus_guess(payload: BonusGuessRequest, session: AsyncSession = Depends(get_session)):
    """Догадка по бонусному слову. Играть можно только пока бонус открыт: в день его открытия, после
    завершения слова этого дня и без пропусков в блоке."""
    entry, tournament = await _bonus_context(session, payload.token, payload.tournament_id)
    state = await _bonus_state_for(session, tournament, entry, payload.number)
    if state["state"] != "open":
        raise HTTPException(status_code=400, detail="Бонусное слово сейчас недоступно")
    dw = await bonus.get_bonus_word(session, tournament.id, payload.number)

    guess = payload.guess.strip().lower()
    length = len(dw.word)
    if len(guess) != length:
        raise HTTPException(status_code=400, detail=f"Слово должно быть из {length} букв")
    if not is_valid_word(guess, length):
        raise HTTPException(status_code=400, detail="Такого слова нет в словаре")

    attempt = await crud.get_or_create_attempt(session, entry.id, dw.id)
    if attempt.solved or attempt.attempts_used >= MAX_ATTEMPTS:
        raise HTTPException(status_code=400, detail="Попытки по бонусному слову исчерпаны")

    statuses = check_guess(guess, dw.word)
    solved = is_solved(statuses)
    attempts_used = attempt.attempts_used + 1
    game_over = solved or attempts_used >= MAX_ATTEMPTS
    points = calculate_points(attempts_used, solved, tournament.scoring_rules or {}) if game_over else None
    saved = await crud.save_guess(session, attempt, guess, solved, game_over, points)

    report_text = None
    if game_over:
        report_text = _bonus_report_text(tournament, entry, payload.number, saved, dw.word)
        if tournament.notify_admin and notify.is_configured():
            try:
                notify.notify_admin_in_background(f"{report_text}\n\n{_notification_footer(datetime.utcnow(), None, None)}")
            except Exception:
                logger.exception("Не удалось подготовить уведомление админу (бонус)")
    return GuessResponse(
        result=[LetterState(letter=g, state=s) for g, s in zip(guess, statuses)],
        solved=solved, attempts_used=attempts_used, attempts_remaining=MAX_ATTEMPTS - attempts_used,
        game_over=game_over, points=points,
        answer_word=dw.word if game_over and not solved else None, report_text=report_text,
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
    if view.get("match_finished") and view.get("won") and not view.get("is_third_place"):
        next_word_at = next_publish_at().isoformat()
    unavailable = {} if view.get("has_match") else _unavailable_info(tournament)
    # tournament_title = "<название> <стадия>" (см. render_tournament_title) —
    # для копируемого отчёта нужны они по отдельности
    stage_label = await _bracket_stage_label(session, tournament, entry, tournament_title)
    report_text = None
    if view.get("has_match") and view.get("already_played") and view.get("attempts_used") is not None:
        report_text = _bracket_report_text(tournament, entry, view, stage_label)
    return BracketTodayStatus(
        **view, callsign=entry.callsign, tournament_title=tournament_title, hashtag=tournament.hashtag,
        next_word_at=next_word_at, base_title=tournament.title, stage_label=stage_label,
        report_text=report_text, **unavailable,
    )


@router.post("/bracket/guess", response_model=GuessResponse)
async def submit_bracket_guess(payload: GuessRequest, session: AsyncSession = Depends(get_session)):
    guess = payload.guess.strip().lower()

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

    # длина догадки — длина слова текущей игры ИМЕННО этого игрока (обязательные игры пары идут подряд;
    # длину задаёт план длин стадии)
    current_game = await bracket_game.current_game_for_entry(session, active_matches[0], entry.id)
    length = len(current_game.word) if current_game is not None else base_length(tournament)
    played_game_number = current_game.game_number if current_game is not None else None
    if len(guess) != length:
        raise HTTPException(status_code=400, detail=f"Слово должно быть из {length} букв")
    if not is_valid_word(guess, length):
        raise HTTPException(status_code=400, detail="Такого слова нет в словаре")

    try:
        statuses, solved, attempts_used, game_over = await bracket_game.submit_guess(
            session, tournament, active_matches[0], entry.id, guess
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if game_over:
        await _notify_bracket_finished(session, tournament, entry, played_game_number)

    next_game = await bracket_game.current_game_for_entry(session, active_matches[0], entry.id) if game_over else None
    return GuessResponse(
        result=[LetterState(letter=g, state=s) for g, s in zip(guess, statuses)],
        solved=solved,
        attempts_used=attempts_used,
        attempts_remaining=MAX_ATTEMPTS - attempts_used,
        game_over=game_over,
        points=None,
        game_number=played_game_number, games_required=active_matches[0].games_required or 1,
        has_next_game=(next_game is not None) if game_over else None,
    )
