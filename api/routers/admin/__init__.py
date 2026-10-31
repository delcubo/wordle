"""Админ-панель: логин, глобальный список игроков, управление розыгрышами разных
типов, подключение игроков к розыгрышу, подтверждение слова дня, таблицы.
Все эндпоинты, кроме /login, защищены require_admin (см. api/admin_auth.py).
(Разбито по областям: auth, dictionary, users, tournaments, entries, ...; роутеры подключаются здесь.)
"""
from fastapi import APIRouter

from api.routers.admin import auth, dictionary, users, tournaments, entries, marathon, teams, standings, bonus, words, tiebreak, bracket

router = APIRouter(prefix="/admin", tags=["admin"])

router.include_router(auth.router)
router.include_router(dictionary.router)
router.include_router(users.router)
router.include_router(tournaments.router)
router.include_router(entries.router)
router.include_router(marathon.router)
router.include_router(teams.router)
router.include_router(standings.router)
router.include_router(bonus.router)
router.include_router(words.router)
router.include_router(tiebreak.router)
router.include_router(bracket.router)
