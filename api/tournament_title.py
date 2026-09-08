"""
Формирование отображаемого названия розыгрыша перед показом игрокам/админу —
в БД title хранится "чистым", без каких-либо плейсхолдеров, админ вводит его
как обычное название. День/стадия добавляются автоматически по правилам:

- knockout — всегда "{title} {стадия}" ("1/4 финала", "финал" и т.п.; до
  генерации сетки — заглушка);
- championship в тай-брейке/плей-офф — так же, как knockout (сетка уже идёт);
- standard, а также championship до тай-брейка/плей-офф — "{title} #деньN"
  (N зажат в границы [1, duration_days], чтобы не показывать нелепые числа
  до старта или после окончания);
- endless — просто "{title}" без добавок (ни дней, ни стадий у неё нет).

round_number — если известен раунд КОНКРЕТНОГО игрока (см. api/routers/game.py),
стадия считается по нему; иначе (например, для общего вида в админке) — по
самому дальнему раунду во всей сетке. Раньше стадия всегда бралась по всей
сетке целиком, из-за чего игрок в ещё не сыгранной паре 1/4 финала видел
"1/2 финала", если другие пары уже прошли дальше — см. пункт бэклога.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentType, TournamentStatus
from api.tournament_time import today, day_number_for_date
from api import crud


async def render_tournament_title(
    session: AsyncSession, tournament: Tournament, round_number: int | None = None
) -> str:
    title = tournament.title
    bracket_phase = tournament.type == TournamentType.knockout or tournament.status in (
        TournamentStatus.tiebreak, TournamentStatus.playoff,
    )

    if bracket_phase:
        return f"{title} {await _current_stage_label(session, tournament, round_number)}"

    if tournament.duration_days is not None:
        day_number = day_number_for_date(tournament.start_date, today())
        day_number = max(1, min(day_number, tournament.duration_days))
        return f"{title} #день{day_number}"

    return title


async def _current_stage_label(
    session: AsyncSession, tournament: Tournament, round_number: int | None = None
) -> str:
    if round_number is None:
        matches = await crud.list_playoff_matches(session, tournament.id)
        if not matches:
            return "скоро начнётся"
        round_number = max(m.round_number for m in matches)

    if tournament.bracket_size is None:
        return "скоро начнётся"

    matches_in_round = tournament.bracket_size // (2 ** round_number)
    if matches_in_round <= 1:
        return "финал"
    if matches_in_round == 2:
        return "1/2 финала"
    return f"1/{matches_in_round} финала"
