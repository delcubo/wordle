"""
Приведение адреса базы к виду, который понимает наш async-движок (asyncpg).

Хостинги выдают адрес Postgres в разных формах: postgres://…, postgresql://…,
иногда с параметром ?sslmode=require (так принято у libpq/psycopg). Приложение
же работает через SQLAlchemy + asyncpg, которому нужен префикс
postgresql+asyncpg:// и параметр ssl вместо sslmode. Чтобы перенос на любой
хостинг не упирался в формат строки, приводим её к нужному виду здесь — и для
приложения (api/database.py), и для миграций (alembic/env.py), и для скриптов
резервного копирования.
"""

_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def normalize_database_url(url: str) -> str:
    url = url.strip()
    # любой синхронный/короткий вариант схемы Postgres -> asyncpg
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break

    if not url.startswith("postgresql+asyncpg://"):
        return url  # sqlite+aiosqlite:// и прочее — как есть

    base, sep, query = url.partition("?")
    if not sep:
        return url
    params = []
    for item in query.split("&"):
        if not item:
            continue
        key, eq, value = item.partition("=")
        if key == "sslmode":
            # asyncpg понимает ssl=<режим>, а sslmode как аргумент соединения — нет
            if value in _SSLMODES:
                params.append(f"ssl={value}")
            continue
        params.append(item)
    return base + ("?" + "&".join(params) if params else "")
