"""Админка: участие игроков в розыгрыше (часть api/routers/admin, см. __init__.py)."""

from datetime import timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, tiebreak
from api.admin_auth import require_admin
from api.database import get_session
from api.models import TournamentEntry, TournamentType, User
from api.modes import has as mode_has
from api.schemas import (
    EntriesTransferRequest,
    EntriesTransferResponse,
    EntryActiveRequest,
    EntryCreateRequest,
    EntryEditRequest,
    EntryHiddenRequest,
    EntryOut,
)

router = APIRouter()


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
    if tournament is None or not mode_has(tournament.type, "tracks_today"):
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

@router.delete("/entries/{entry_id}")
async def delete_tiebreak_entry(entry_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    """Удалить игрока из тай-брейка совсем (в отличие от «Отключить» — его результаты стираются, он
    пропадает из таблицы и распределения мест). Только для розыгрышей типа «тай-брейк»; необратимо."""
    entry = await session.get(TournamentEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Участие не найдено")
    tournament = await crud.get_tournament(session, entry.tournament_id)
    if tournament is None or tournament.type != TournamentType.tiebreak:
        raise HTTPException(status_code=400, detail="Удалять игрока из розыгрыша можно только в тай-брейке")
    await tiebreak.remove_entry(session, tournament, entry_id)
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
