"""
Единственный администратор (вы) — поэтому полноценная система пользователей не
нужна. Логика простая: пароль сверяется с ADMIN_PASSWORD из переменных окружения,
при успехе выдаётся подписанный cookie-токен (itsdangerous), который проверяется
на всех /admin/* эндпоинтах, кроме /admin/login.
"""
import hmac
import os
import time

from fastapi import Request, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
COOKIE_NAME = "admin_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7 дней

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="admin-session")


def check_password(password: str) -> bool:
    if not ADMIN_PASSWORD:
        # если пароль не задан в конфиге — считаем, что админ-доступ ещё не настроен,
        # и явно отказываем, а не пропускаем всех подряд.
        return False
    # постоянное время сравнения — не даёт подбирать пароль по времени ответа
    return hmac.compare_digest(password.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8"))


# Ограничение неудачных попыток входа по IP (см. пункт бэклога про защиту
# админки): счётчик в памяти процесса — сервис один, при деплое сбрасывается.
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
_login_failures: dict[str, list[float]] = {}
_MAX_TRACKED_IPS = 10000


def client_ip(request: Request) -> str:
    """
    IP клиента за прокси Railway: берём ПРАВЫЙ элемент X-Forwarded-For — его
    дописывает доверенный прокси, а левые элементы клиент может подделать
    (иначе блокировку обходили бы случайным заголовком). Без заголовка (локальная
    разработка) — адрес прямого соединения.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _recent_failures(ip: str, now: float) -> list[float]:
    recent = [t for t in _login_failures.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    if recent:
        _login_failures[ip] = recent
    else:
        _login_failures.pop(ip, None)
    return recent


def login_retry_after(ip: str) -> int:
    """Сколько секунд ещё нельзя пробовать войти с этого IP (0 — можно)."""
    now = time.time()
    recent = _recent_failures(ip, now)
    if len(recent) < LOGIN_MAX_FAILS:
        return 0
    return max(1, int(LOGIN_WINDOW_SECONDS - (now - recent[0])) + 1)


def record_login_failure(ip: str) -> None:
    now = time.time()
    if len(_login_failures) >= _MAX_TRACKED_IPS and ip not in _login_failures:
        # защита памяти от переполнения чужими IP — выкидываем самые старые записи
        for old_ip in sorted(_login_failures, key=lambda k: _login_failures[k][-1])[: _MAX_TRACKED_IPS // 10]:
            _login_failures.pop(old_ip, None)
    _recent_failures(ip, now)
    _login_failures.setdefault(ip, []).append(now)


def clear_login_failures(ip: str) -> None:
    _login_failures.pop(ip, None)


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
