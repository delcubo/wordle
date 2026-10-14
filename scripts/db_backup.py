"""
Резервная копия базы в обычный JSON-файл и восстановление из него — независимо
от хостинга (работает с любой базой, к которой есть адрес).

Зачем: данные игры (игроки, розыгрыши, результаты) не должны зависеть от одного
хостера. Копия — это один файл, который можно хранить у себя на компьютере.

  python scripts/db_backup.py dump    [--url АДРЕС] [--out ФАЙЛ]
  python scripts/db_backup.py restore --in ФАЙЛ [--url АДРЕС] [--ignore-version]

--url можно не указывать — тогда берётся DATABASE_URL из окружения (формат
любой: postgres://…, postgresql://…, ?sslmode=… — см. api/db_url.py).

restore кладёт данные в ПУСТУЮ базу, в которой уже накатаны миграции
(`alembic upgrade head`): непустую базу он не трогает. После вставки
выравнивает счётчики id у Postgres.

ВНИМАНИЕ: в копии лежат личные ссылки игроков (access_token) и всё содержимое
базы — храните файл как секрет и не коммитьте его (папка backups/ в .gitignore).
"""
import argparse
import asyncio
import enum
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import Date, DateTime, select, text, func  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from api.db_url import normalize_database_url  # noqa: E402

FORMAT_VERSION = 1
Base = None  # заполняется в _setup — после того, как известен адрес базы


def _setup(url: str | None) -> str:
    """api.database создаёт соединение сразу при импорте, по DATABASE_URL, поэтому
    сначала выставляем нужный адрес, и только потом подключаем модели."""
    global Base
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Не задан адрес базы: укажите --url или переменную окружения DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    from api.database import Base as _Base
    from api import models  # noqa: F401 — регистрирует все таблицы в Base.metadata
    Base = _Base
    return normalize_database_url(url)


def _engine(url: str):
    return create_async_engine(url)


def _to_jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.name  # в базе хранится имя члена перечисления
    return value


def _from_jsonable(table, row: dict) -> dict:
    result = {}
    for key, value in row.items():
        column = table.c[key]
        if value is not None and isinstance(column.type, DateTime):
            value = datetime.fromisoformat(value)
        elif value is not None and isinstance(column.type, Date):
            value = date.fromisoformat(value)
        result[key] = value
    return result


async def _alembic_version(conn):
    try:
        return (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    except Exception:
        return None


async def dump(url: str | None, out: Path) -> None:
    engine = _engine(_setup(url))
    data: dict = {}
    async with engine.connect() as conn:
        version = await _alembic_version(conn)
        for table in Base.metadata.sorted_tables:
            rows = (await conn.execute(select(table))).mappings().all()
            data[table.name] = [{k: _to_jsonable(v) for k, v in row.items()} for row in rows]
    await engine.dispose()

    payload = {
        "format": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "alembic_version": version,
        "tables": data,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    counts = ", ".join(f"{name}: {len(rows)}" for name, rows in data.items() if rows)
    print(f"Копия сохранена: {out} ({out.stat().st_size // 1024} КБ)")
    print(f"Версия миграций: {version}. Строк по таблицам: {counts or 'пусто'}")


async def restore(url: str | None, src: Path, ignore_version: bool) -> None:
    payload = json.loads(src.read_text(encoding="utf-8"))
    if payload.get("format") != FORMAT_VERSION:
        sys.exit(f"Неизвестный формат копии: {payload.get('format')}")

    engine = _engine(_setup(url))
    async with engine.begin() as conn:
        target_version = await _alembic_version(conn)
        if not ignore_version and target_version != payload.get("alembic_version"):
            sys.exit(
                f"Версия схемы в базе ({target_version}) не совпадает с копией ({payload.get('alembic_version')}). "
                "Накатите миграции (`alembic upgrade head`) или используйте --ignore-version, если уверены."
            )
        for table in Base.metadata.sorted_tables:
            if (await conn.execute(select(func.count()).select_from(table))).scalar_one():
                sys.exit(f"База не пустая (таблица {table.name}) — восстановление отменено, ничего не изменено.")

        restored = {}
        for table in Base.metadata.sorted_tables:
            rows = payload["tables"].get(table.name, [])
            if rows:
                await conn.execute(table.insert(), [_from_jsonable(table, row) for row in rows])
                restored[table.name] = len(rows)

        if conn.dialect.name == "postgresql":
            for table in Base.metadata.sorted_tables:
                if "id" in table.c and restored.get(table.name):
                    await conn.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), (SELECT MAX(id) FROM {table.name}))"
                    ))
    await engine.dispose()
    print("Восстановлено строк по таблицам:", ", ".join(f"{k}: {v}" for k, v in restored.items()) or "ничего")


def main() -> None:
    parser = argparse.ArgumentParser(description="Резервная копия и восстановление базы Вордли")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="сохранить копию базы в JSON-файл")
    p_dump.add_argument("--url", help="адрес базы (по умолчанию DATABASE_URL)")
    p_dump.add_argument("--out", type=Path, help="куда сохранить (по умолчанию backups/wordle-<дата>.json)")

    p_restore = sub.add_parser("restore", help="загрузить копию в пустую базу")
    p_restore.add_argument("--in", dest="src", type=Path, required=True, help="файл копии")
    p_restore.add_argument("--url", help="адрес базы (по умолчанию DATABASE_URL)")
    p_restore.add_argument("--ignore-version", action="store_true", help="не сверять версию миграций")

    args = parser.parse_args()
    if args.command == "dump":
        out = args.out or Path("backups") / f"wordle-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        asyncio.run(dump(args.url, out))
    else:
        asyncio.run(restore(args.url, args.src, args.ignore_version))


if __name__ == "__main__":
    main()
