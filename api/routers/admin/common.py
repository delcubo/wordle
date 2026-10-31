"""Админка: общие помощники (часть api/routers/admin, см. __init__.py)."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud
from api.models import Tournament, TournamentType
from api.schemas import TournamentOut
from api.tournament_time import effective_status


def _tournament_out(tournament: Tournament) -> TournamentOut:
    """status — вычисленный (см. api.tournament_time.effective_status), а не
    сырое поле из БД: ручной активации больше нет, draft/active выводятся из
    даты старта на лету (см. пункт бэклога)."""
    return TournamentOut.model_validate(tournament).model_copy(update={"status": effective_status(tournament).value})

async def _get_marathon(session: AsyncSession, tournament_id: int) -> Tournament:
    tournament = await crud.get_tournament(session, tournament_id)
    if tournament is None:
        raise HTTPException(status_code=404, detail="Розыгрыш не найден")
    if tournament.type != TournamentType.marathon:
        raise HTTPException(status_code=400, detail="Это не марафон")
    return tournament
