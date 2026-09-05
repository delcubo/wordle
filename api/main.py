import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routers import game, admin

app = FastAPI(title="Wordle Group Game API")

app.include_router(game.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

WEBAPP_DIST = os.path.join(os.path.dirname(__file__), "..", "webapp", "dist")
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
    """
    if os.path.isfile(_index_path):
        return FileResponse(_index_path)
    return {"detail": "Webapp not built yet — run `npm run build` in webapp/"}
