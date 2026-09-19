import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.database import async_session_factory
from api.dictionary import register_added_word
from api.routers import game, admin
from api import crud

# Автодокументация (/docs, /redoc, /openapi.json) раскрывает список всех
# эндпоинтов, включая админские, — включается только явно (ENABLE_DOCS=1).
_docs_enabled = os.environ.get("ENABLE_DOCS") == "1"
app = FastAPI(
    title="Wordle Group Game API",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


app.include_router(game.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.on_event("startup")
async def _load_added_words_into_dictionary_cache():
    """Слова, добавленные админом вручную (см. AddedWord), хранятся в БД, а не
    в файле репозитория — при старте каждого процесса подгружаем их в кэш
    словаря заново (см. api/dictionary.py::register_added_word)."""
    async with async_session_factory() as session:
        for word in await crud.list_added_words(session):
            register_added_word(word.word)

WEBAPP_DIST = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "webapp", "dist"))
_index_path = os.path.join(WEBAPP_DIST, "index.html")
_assets_dir = os.path.join(WEBAPP_DIST, "assets")

if os.path.isdir(_assets_dir):
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """
    Единственная страница (index.html) обслуживает весь клиентский роутинг
    (/, /login, /play/<token>) — React Router на фронте решает, что показать.
    Не перехватывает /api/* и /assets/*, так как они зарегистрированы выше
    и совпадают раньше в порядке маршрутизации Starlette.

    Реальные статические файлы из webapp/public (favicon.svg и т.п. — Vite
    копирует их в корень dist при сборке, не в assets/) отдаются как есть,
    если такой файл действительно есть на диске — иначе браузер вместо иконки
    получал бы этот же index.html и молча падал обратно на дефолтную иконку
    вкладки. os.path.realpath — защита от выхода за пределы dist через "..".
    """
    candidate = os.path.realpath(os.path.join(WEBAPP_DIST, full_path))
    if full_path and candidate.startswith(WEBAPP_DIST + os.sep) and os.path.isfile(candidate):
        return FileResponse(candidate)
    if os.path.isfile(_index_path):
        return FileResponse(_index_path)
    return {"detail": "Webapp not built yet — run `npm run build` in webapp/"}
