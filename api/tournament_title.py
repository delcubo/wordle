"""
Формирование отображаемого названия розыгрыша перед показом игрокам/админу —
в БД title хранится "чистым", без каких-либо плейсхолдеров, админ вводит его
как обычное название. День/стадия добавляются автоматически по правилам:

- knockout — всегда "{title} {стадия}" ("1/4 финала", "финал" и т.п., по
  последнему существующему раунду; до генерации сетки — заглушка);
- championship в тай-брейке/плей-офф — так же, как knockout (сетка уже идёт);
- standard, а также championship до тай-брейка/плей-офф — "{title} #деньN"
  (N зажат в границы [1, duration_days], чтобы не показывать нелепые числа
  до старта или после окончания);
- endless — просто "{title}" без добавок (ни дней, ни стадий у неё нет).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentType, TournamentStatus
from api.tournament_time import today, day_number_for_date
from api import crud


async def render_tournament_title(session: AsyncSession, tournament: Tournament) -> str:
    title = tournament.title
    bracket_phase = tournament.type == TournamentType.knockout or tournament.status in (
        TournamentStatus.tiebreak, TournamentStatus.playoff,
    )

    if bracket_phase:
        return f"{title} {await _current_stage_label(session, tournament)}"

    if tournament.duration_days is not None:
        day_number = day_number_for_date(tournament.start_date, today())
        day_number = max(1, min(day_number, tournament.duration_days))
        return f"{title} #день{day_number}"

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
