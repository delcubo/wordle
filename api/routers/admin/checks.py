"""Админка: окно «Проверка» результата игрока (часть api/routers/admin, см. __init__.py и api/attempt_check.py)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin_auth import require_admin
from api.attempt_check import build_attempt_check
from api.database import get_session
from api.models import DailyWord, TournamentEntry

router = APIRouter()


@router.get("/entries/{entry_id}/attempt-check")
async def get_attempt_check(
    entry_id: int, word_id: int, session: AsyncSession = Depends(get_session), _: None = Depends(require_admin)
):
    """Факты для оценки результата игрока по слову word_id: история ввода этого слова, кто закончил раньше,
    статистика «1/6» (подсказки без вывода — решает админ)."""
    entry = await session.get(TournamentEntry, entry_id)
    word = await session.get(DailyWord, word_id)
    if entry is None or word is None:
        raise HTTPException(status_code=404, detail="Участие или слово не найдено")
    try:
        return await build_attempt_check(session, entry, word)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
