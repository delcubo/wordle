"""Админка: розыгрыши: создание, настройки, план слов, реестр режимов, «Сегодня» (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import bonus, bracket_game, crud, marathon, word_plan as wp
from api.admin_auth import require_admin
from api.database import get_session
from api.dictionary import SUPPORTED_LENGTHS
from api.models import Tournament, TournamentStatus, TournamentType
from api.modes import has as mode_has, modes_out
from api.routers.admin.common import _tournament_out
from api.schemas import (
    TournamentArchiveRequest,
    TournamentConfigRequest,
    TournamentOut,
    TournamentPauseRequest,
    TournamentSettingsUpdateRequest,
    WordPlanRequest,
)
from api.today_view import build_today
from api.tournament_time import day_number_for_date, today

router = APIRouter()


@router.post("/tournaments", response_model=TournamentOut)
async def create_tournament(
    payload: TournamentConfigRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    try:
        t_type = TournamentType(payload.type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неизвестный тип розыгрыша")

    if mode_has(t_type, "duration") and not payload.duration_days:
        raise HTTPException(status_code=400, detail="Для этого типа розыгрыша нужно указать длительность в днях")

    if payload.bracket_size is not None:
        n = payload.bracket_size
        if n <= 0 or (n & (n - 1)) != 0:
            raise HTTPException(status_code=400, detail="Размер сетки должен быть степенью двойки")
    if t_type == TournamentType.knockout and not payload.bracket_size:  # у чемпионата размер необязателен: берётся из итогов
        raise HTTPException(status_code=400, detail="Для розыгрыша на вылет нужно указать размер сетки")

    if payload.word_length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина слов должна быть 5, 6 или 7 букв")
    if payload.bonus_default_length not in SUPPORTED_LENGTHS:
        raise HTTPException(status_code=400, detail="Длина бонусных слов должна быть 5, 6 или 7 букв")
    if payload.bonus_enabled:
        if not mode_has(t_type, "bonus"):
            raise HTTPException(status_code=400, detail="Бонусные слова есть только у Стандартного режима и Чемпионата")
        if not payload.bonus_every_days or not (1 <= payload.bonus_every_days <= (payload.duration_days or 0)):
            raise HTTPException(status_code=400, detail="N (бонус за каждые N дней) — от 1 до длительности розыгрыша")

    if mode_has(t_type, "words_count"):
        if payload.words_count is None or not (marathon.MIN_WORDS <= payload.words_count <= marathon.MAX_WORDS):
            raise HTTPException(
                status_code=400, detail=f"Число слов должно быть от {marathon.MIN_WORDS} до {marathon.MAX_WORDS}"
            )
        if payload.end_date is not None and payload.end_date < payload.start_date:
            raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты старта")

    if t_type == TournamentType.tiebreak:
        if payload.end_date is not None and payload.end_date < payload.start_date:
            raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты старта")
    elif not mode_has(t_type, "end_date") and payload.end_date is not None:
        raise HTTPException(status_code=400, detail="Дата окончания задаётся только у марафона и тай-брейка")

    if t_type == TournamentType.endless:
        # ручной активации больше нет — проверяем сразу при создании, чтобы не
        # завести вторую бессрочную игру, которая рано или поздно (по дате
        # старта) сама начнёт выдавать слова параллельно с текущей
        other = await crud.get_other_active_tournament_of_type(session, TournamentType.endless)
        if other is not None:
            raise HTTPException(status_code=400, detail=f"Уже идёт бессрочная игра «{other.title}» — сначала завершите её")

    tournament = Tournament(
        title=payload.title,
        type=t_type,
        start_date=payload.start_date,
        duration_days=payload.duration_days if mode_has(t_type, "duration") else None,
        scoring_rules=payload.scoring_rules if mode_has(t_type, "scoring") else None,
        words_count=payload.words_count if mode_has(t_type, "words_count") else None,
        end_date=payload.end_date if mode_has(t_type, "end_date") else None,
        individual_words=bool(payload.individual_words) and mode_has(t_type, "individual_words"),
        word_length=payload.word_length,
        bonus_enabled=bool(payload.bonus_enabled),
        bonus_every_days=payload.bonus_every_days if payload.bonus_enabled else None,
        bonus_default_length=payload.bonus_default_length,
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
    if tournament.bonus_enabled:
        await _sync_bonus_words(session, tournament)
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
        if "playoff_games" in plan and tournament.type not in (TournamentType.championship, TournamentType.knockout):
            raise HTTPException(status_code=400, detail="Число игр по стадиям — только для розыгрышей с сеткой плей-офф")
        if "tiebreak" in plan and tournament.type not in (TournamentType.tiebreak, TournamentType.championship):
            raise HTTPException(status_code=400, detail="План по раундам — только для тай-брейка")
    tournament.word_plan = plan
    session.add(tournament)
    await session.commit()
    if tournament.type == TournamentType.marathon:
        await marathon.apply_lengths(session, tournament)
    if tournament.type in (TournamentType.championship, TournamentType.knockout):
        await bracket_game.sync_games_required(session, tournament)  # ещё не начатые пары — под новый план
    await session.refresh(tournament)
    return _tournament_out(tournament)

async def _sync_bonus_words(session: AsyncSession, tournament: Tournament) -> None:
    """Создать/убрать бонусные слова по настройкам розыгрыша; ошибки словаря и «уже начато» — как 400."""
    try:
        await bonus.sync_words(session, tournament)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError:
        raise HTTPException(status_code=400, detail="В словаре не хватает слов нужной длины для бонусов")

@router.get("/modes")
async def get_modes(_: None = Depends(require_admin)):
    """Реестр режимов: название, описание и набор модулей каждого (см. api/modes.py) — по нему админка
    строит мастер создания розыгрыша, форму настроек, подвкладки и панели."""
    return modes_out()

@router.get("/today")
async def get_today(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Экран «Сегодня»: по карточке на идущий розыгрыш — сколько закончили, результаты, слово на завтра
    (см. api/today_view.py)."""
    return await build_today(session)

@router.get("/tournaments", response_model=list[TournamentOut])
async def get_tournaments(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    connected = await crud.count_connected_entries(session)
    return [
        _tournament_out(t).model_copy(update={"players_connected": connected.get(t.id, 0)})
        for t in await crud.list_tournaments(session)
    ]

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

    bonus_changed = (
        payload.bonus_enabled is not None or payload.bonus_every_days is not None
        or payload.bonus_default_length is not None
    )
    if bonus_changed:
        if not bonus.supports_bonus(tournament):
            raise HTTPException(status_code=400, detail="Бонусные слова есть только у Стандартного режима и Чемпионата")
        new_enabled = tournament.bonus_enabled if payload.bonus_enabled is None else payload.bonus_enabled
        new_every = tournament.bonus_every_days if payload.bonus_every_days is None else payload.bonus_every_days
        new_length = tournament.bonus_default_length if payload.bonus_default_length is None else payload.bonus_default_length
        if new_length not in SUPPORTED_LENGTHS:
            raise HTTPException(status_code=400, detail="Длина бонусных слов должна быть 5, 6 или 7 букв")
        if new_enabled and (not new_every or not (1 <= new_every <= tournament.duration_days)):
            raise HTTPException(status_code=400, detail="N (бонус за каждые N дней) — от 1 до длительности розыгрыша")
        if (
            (new_enabled != bool(tournament.bonus_enabled) or (new_enabled and new_every != tournament.bonus_every_days))
            and await bonus.any_bonus_attempts(session, tournament.id)
        ):
            raise HTTPException(status_code=400, detail="Бонусные слова уже начаты — включать, выключать и менять N поздно")
        tournament.bonus_enabled = new_enabled
        tournament.bonus_every_days = new_every if new_enabled else None
        tournament.bonus_default_length = new_length

    session.add(tournament)
    await session.commit()
    await session.refresh(tournament)
    if bonus_changed or (payload.duration_days is not None and tournament.bonus_enabled):
        await _sync_bonus_words(session, tournament)
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
