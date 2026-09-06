"""
Подстановка динамических плейсхолдеров в название розыгрыша перед показом
игрокам/админу — сам title в БД хранится с плейсхолдерами как есть.

{day}   — текущий день розыгрыша (standard/championship), зажат в границы
          [1, duration_days], чтобы не показывать нелепые числа до старта
          или после окончания.
{stage} — текущая стадия сетки (knockout) — "1/4 финала", "финал" и т.п.,
          по последнему существующему раунду; до генерации сетки — заглушка.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentType
from api.tournament_time import today, day_number_for_date
from api import crud


async def render_tournament_title(session: AsyncSession, tournament: Tournament) -> str:
    title = tournament.title

    if "{day}" in title and tournament.duration_days is not None:
        day_number = day_number_for_date(tournament.start_date, today())
        day_number = max(1, min(day_number, tournament.duration_days))
        title = title.replace("{day}", str(day_number))

    if "{stage}" in title and tournament.type == TournamentType.knockout:
        title = title.replace("{stage}", await _current_stage_label(session, tournament))

    return title


async def _current_stage_label(session: AsyncSession, tournament: Tournament) -> str:
    matches = await crud.list_playoff_matches(session, tournament.id)
    if not matches or tournament.bracket_size is None:
        return "скоро начнётся"

    latest_round = max(m.round_number for m in matches)
    matches_in_round = tournament.bracket_size // (2 ** latest_round)
    if matches_in_round <= 1:
        return "финал"
    if matches_in_round == 2:
        return "1/2 финала"
    return f"1/{matches_in_round} финала"
