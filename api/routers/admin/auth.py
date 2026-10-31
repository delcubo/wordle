"""Админка: вход, выход, тема, тест Telegram (часть api/routers/admin, см. __init__.py)."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, notify
from api.admin_auth import (
    check_password,
    clear_login_failures,
    client_ip,
    COOKIE_NAME,
    create_session_token,
    login_retry_after,
    record_login_failure,
    require_admin,
    SESSION_MAX_AGE_SECONDS,
)
from api.database import get_session
from api.schemas import AdminLoginRequest, ThemeOut, ThemeUpdateRequest

router = APIRouter()


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
