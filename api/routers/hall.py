"""
Зал славы: летопись чемпионов прошедших турниров. Игрок видит страницу по своей
персональной ссылке (если зал открыт), админ ведёт записи и картинки из админки.

Доступность задаёт AppSettings.hall_mode: "off" — никому, "test" — только
игроку hall_test_user_id (проверка перед открытием), "on" — всем игрокам.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud
from api.admin_auth import require_admin
from api.database import get_session
from api.models import AppSettings, HallEntry, HallImage, User

player_router = APIRouter(prefix="/game/hall", tags=["hall"])
admin_router = APIRouter(prefix="/admin/hall", tags=["hall-admin"])

HALL_MODES = ("off", "test", "on")
IMAGE_KINDS = ("table", "bracket", "certificate")
MAX_IMAGE_BYTES = 3 * 1024 * 1024
UNAVAILABLE = "Зал славы пока недоступен"


# ---------- Схемы ----------

class HallEntryOut(BaseModel):
    id: int
    title: str
    champion: str
    date_start: date
    date_end: date
    is_current: bool  # итоговый флаг: уже с учётом правила "если не отмечено — самый поздний"
    table_image_id: int | None = None
    bracket_image_id: int | None = None
    certificate_image_id: int | None = None


class HallOut(BaseModel):
    entries: list[HallEntryOut]  # от новых к старым


class HallStatusOut(BaseModel):
    available: bool


class HallSettingsOut(BaseModel):
    mode: str
    test_user_id: int | None = None


class HallSettingsRequest(BaseModel):
    mode: str
    test_user_id: int | None = None


class HallEntryRequest(BaseModel):
    title: str
    champion: str
    date_start: date
    date_end: date
    is_current: bool = False


# ---------- Общее ----------

def _is_available(settings: AppSettings, user_id: int) -> bool:
    return settings.hall_mode == "on" or (
        settings.hall_mode == "test" and settings.hall_test_user_id == user_id
    )


async def _read_settings(session: AsyncSession) -> AppSettings:
    """Настройки только для чтения: если строки ещё нет — значения по умолчанию,
    но строка НЕ создаётся (иначе два параллельных запроса игрока при первом
    обращении, например вместе с /game/theme, оба пытались бы её вставить)."""
    return await session.get(AppSettings, 1) or AppSettings(id=1, theme="dark", hall_mode="off")


async def _player(session: AsyncSession, token: str) -> User:
    user = await crud.get_user_by_token(session, token)
    if user is None or user.archived:
        raise HTTPException(status_code=404, detail="Ссылка недействительна")
    return user


async def _list_entries(session: AsyncSession) -> list[HallEntry]:
    result = await session.execute(
        select(HallEntry).order_by(HallEntry.date_end.desc(), HallEntry.id.desc())
    )
    return list(result.scalars().all())


def _to_out(entries: list[HallEntry]) -> list[HallEntryOut]:
    # список уже отсортирован от новых к старым: если никто не отмечен вручную,
    # действующий чемпион — первый
    flagged = [e for e in entries if e.is_current]
    current_id = (flagged[0].id if flagged else (entries[0].id if entries else None))
    return [
        HallEntryOut(
            id=e.id, title=e.title, champion=e.champion, date_start=e.date_start, date_end=e.date_end,
            is_current=(e.id == current_id),
            table_image_id=e.table_image_id, bracket_image_id=e.bracket_image_id,
            certificate_image_id=e.certificate_image_id,
        )
        for e in entries
    ]


def _image_response(image: HallImage) -> Response:
    return Response(
        content=image.data, media_type=image.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_entry(payload: HallEntryRequest) -> tuple[str, str]:
    title = payload.title.strip()
    champion = payload.champion.strip()
    if not title or not champion:
        raise HTTPException(status_code=400, detail="Название и чемпион обязательны")
    if payload.date_end < payload.date_start:
        raise HTTPException(status_code=400, detail="Дата окончания раньше даты начала")
    return title, champion


# ---------- Игрок ----------

@player_router.get("/status", response_model=HallStatusOut)
async def hall_status(token: str, session: AsyncSession = Depends(get_session)):
    user = await _player(session, token)
    settings = await _read_settings(session)
    return HallStatusOut(available=_is_available(settings, user.id))


@player_router.get("", response_model=HallOut)
async def hall(token: str, session: AsyncSession = Depends(get_session)):
    user = await _player(session, token)
    settings = await _read_settings(session)
    if not _is_available(settings, user.id):
        raise HTTPException(status_code=403, detail=UNAVAILABLE)
    return HallOut(entries=_to_out(await _list_entries(session)))


@player_router.get("/image/{image_id}")
async def hall_image(image_id: int, token: str, session: AsyncSession = Depends(get_session)):
    user = await _player(session, token)
    settings = await _read_settings(session)
    if not _is_available(settings, user.id):
        raise HTTPException(status_code=403, detail=UNAVAILABLE)
    image = await session.get(HallImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Картинка не найдена")
    return _image_response(image)


# ---------- Админ ----------

@admin_router.get("/settings", response_model=HallSettingsOut)
async def get_settings(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    settings = await crud.get_app_settings(session)
    return HallSettingsOut(mode=settings.hall_mode, test_user_id=settings.hall_test_user_id)


@admin_router.put("/settings", response_model=HallSettingsOut)
async def put_settings(
    payload: HallSettingsRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    if payload.mode not in HALL_MODES:
        raise HTTPException(status_code=400, detail="Режим может быть только off, test или on")
    if payload.test_user_id is not None and await session.get(User, payload.test_user_id) is None:
        raise HTTPException(status_code=404, detail="Игрок не найден")
    if payload.mode == "test" and payload.test_user_id is None:
        raise HTTPException(status_code=400, detail="Для тестового режима выберите игрока")
    settings = await crud.get_app_settings(session)
    settings.hall_mode = payload.mode
    settings.hall_test_user_id = payload.test_user_id
    session.add(settings)
    await session.commit()
    return HallSettingsOut(mode=settings.hall_mode, test_user_id=settings.hall_test_user_id)


@admin_router.get("/entries", response_model=HallOut)
async def admin_list_entries(session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    return HallOut(entries=_to_out(await _list_entries(session)))


async def _clear_current_flag(session: AsyncSession, except_id: int | None) -> None:
    for e in await _list_entries(session):
        if e.is_current and e.id != except_id:
            e.is_current = False
            session.add(e)


@admin_router.post("/entries", response_model=HallOut)
async def create_entry(
    payload: HallEntryRequest, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    title, champion = _validate_entry(payload)
    entry = HallEntry(
        title=title, champion=champion, date_start=payload.date_start, date_end=payload.date_end,
        is_current=payload.is_current,
    )
    session.add(entry)
    await session.flush()
    if payload.is_current:
        await _clear_current_flag(session, entry.id)
    await session.commit()
    return HallOut(entries=_to_out(await _list_entries(session)))


@admin_router.patch("/entries/{entry_id}", response_model=HallOut)
async def update_entry(
    entry_id: int, payload: HallEntryRequest,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    entry = await session.get(HallEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    entry.title, entry.champion = _validate_entry(payload)
    entry.date_start = payload.date_start
    entry.date_end = payload.date_end
    entry.is_current = payload.is_current
    session.add(entry)
    if payload.is_current:
        await _clear_current_flag(session, entry.id)
    await session.commit()
    return HallOut(entries=_to_out(await _list_entries(session)))


async def _delete_image_if_any(session: AsyncSession, image_id: int | None) -> None:
    if image_id is not None:
        image = await session.get(HallImage, image_id)
        if image is not None:
            await session.delete(image)


@admin_router.delete("/entries/{entry_id}", response_model=HallOut)
async def delete_entry(entry_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    entry = await session.get(HallEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    image_ids = [entry.table_image_id, entry.bracket_image_id, entry.certificate_image_id]
    await session.delete(entry)
    await session.flush()
    for image_id in image_ids:
        await _delete_image_if_any(session, image_id)
    await session.commit()
    return HallOut(entries=_to_out(await _list_entries(session)))


@admin_router.post("/entries/{entry_id}/images/{kind}", response_model=HallOut)
async def upload_image(
    entry_id: int, kind: str, request: Request,
    session: AsyncSession = Depends(get_session), _: None = Depends(require_admin),
):
    """Тело запроса — сам файл (PNG / JPEG / WebP, до 3 МБ); тип определяется по
    содержимому, а не по заголовку. Новая картинка заменяет прежнюю."""
    if kind not in IMAGE_KINDS:
        raise HTTPException(status_code=400, detail="Тип картинки: table, bracket или certificate")
    entry = await session.get(HallEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Картинка больше 3 МБ")
    data = await request.body()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Картинка больше 3 МБ")
    content_type = _detect_image_type(data)
    if content_type is None:
        raise HTTPException(status_code=400, detail="Нужен файл PNG, JPEG или WebP")

    image = HallImage(content_type=content_type, data=data)
    session.add(image)
    await session.flush()
    field = f"{kind}_image_id"
    old_id = getattr(entry, field)
    setattr(entry, field, image.id)
    session.add(entry)
    await session.flush()
    await _delete_image_if_any(session, old_id)
    await session.commit()
    return HallOut(entries=_to_out(await _list_entries(session)))


@admin_router.delete("/entries/{entry_id}/images/{kind}", response_model=HallOut)
async def delete_image(
    entry_id: int, kind: str, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    if kind not in IMAGE_KINDS:
        raise HTTPException(status_code=400, detail="Тип картинки: table, bracket или certificate")
    entry = await session.get(HallEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    field = f"{kind}_image_id"
    old_id = getattr(entry, field)
    setattr(entry, field, None)
    session.add(entry)
    await session.flush()
    await _delete_image_if_any(session, old_id)
    await session.commit()
    return HallOut(entries=_to_out(await _list_entries(session)))


@admin_router.get("/image/{image_id}")
async def admin_image(image_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)):
    image = await session.get(HallImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Картинка не найдена")
    return _image_response(image)
