"""Админка: игроки (часть api/routers/admin, см. __init__.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud
from api.admin_auth import require_admin
from api.database import get_session
from api.models import User
from api.schemas import UserArchiveRequest, UserCreateRequest, UserEditRequest, UserOut, UserTournamentInfo

router = APIRouter()


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
