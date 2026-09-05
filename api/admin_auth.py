"""
Единственный администратор (вы) — поэтому полноценная система пользователей не
нужна. Логика простая: пароль сверяется с ADMIN_PASSWORD из переменных окружения,
при успехе выдаётся подписанный cookie-токен (itsdangerous), который проверяется
на всех /admin/* эндпоинтах, кроме /admin/login.
"""
import os

from fastapi import Request, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
COOKIE_NAME = "admin_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 дней

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="admin-session")


def check_password(password: str) -> bool:
    if not ADMIN_PASSWORD:
        # если пароль не задан в конфиге — считаем, что админ-доступ ещё не настроен,
        # и явно отказываем, а не пропускаем всех подряд.
        return False
    return password == ADMIN_PASSWORD


def create_session_token() -> str:
    return _serializer.dumps({"admin": True})


def verify_session_token(token: str) -> bool:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return bool(data.get("admin"))


def require_admin(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not token or not verify_session_token(token):
        raise HTTPException(status_code=401, detail="Требуется вход администратора")
