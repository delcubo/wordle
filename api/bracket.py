"""
Генерация раунда 1 сетки плей-офф на выбывание. Championship и knockout
используют одну и ту же модель PlayoffMatch, но заполняются по-разному:
championship — автоматически, по итоговому порядку после основного этапа
и тай-брейка (см. api/tiebreak.compute_final_order); knockout — вручную,
парами, которые задаёт администратор (нет предварительного рейтинга для
автопосева).

Игра самих матчей (подача попыток, sudden death, продвижение по раундам) —
отдельный этап, не этот модуль.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentType, TournamentStatus, PlayoffMatch
from api.tournament_time import today, day_number_for_date
from api.tiebreak import compute_final_order
from api import crud


async def generate_championship_bracket(session: AsyncSession, tournament: Tournament) -> list[PlayoffMatch]:
    """
    Автоматический посев раунда 1: 1 против N, 2 против N-1, ... — классическая
    сетка по итоговому месту. Требует, чтобы основной этап уже завершился и
    все нужные тай-брейки были разрешены (compute_final_order сама бросит
    ValueError, если это не так).
    """
    if tournament.type != TournamentType.championship:
        raise ValueError("Автопосев доступен только для championship")
    if tournament.bracket_size is None:
        raise ValueError("У этого розыгрыша не задан размер сетки плей-офф")
    if tournament.duration_days is None:
        raise ValueError("У этого розыгрыша нет основного этапа")
    day_number = day_number_for_date(tournament.start_date, today())
    if day_number <= tournament.duration_days:
        raise ValueError("Основной этап ещё не завершён")
    if await crud.list_playoff_matches(session, tournament.id):
        raise ValueError("Сетка для этого розыгрыша уже создана")

    order = await compute_final_order(session, tournament)
    n = tournament.bracket_size
    if len(order) < n:
        raise ValueError(f"В розыгрыше {len(order)} участников — меньше, чем размер сетки ({n})")
    seeded = order[:n]

    pairs = [(seeded[i], seeded[n - 1 - i]) for i in range(n // 2)]
    matches = await _create_round(session, tournament.id, round_number=1, pairs=pairs, scheduled_date=today())

    tournament.status = TournamentStatus.playoff
    session.add(tournament)
    await session.commit()
    return matches


async def set_knockout_round1(
    session: AsyncSession, tournament: Tournament, pairs: list[tuple[int, int]]
) -> list[PlayoffMatch]:
    """Ручной посев раунда 1 для knockout — администратор сам расставляет пары."""
    if tournament.type != TournamentType.knockout:
        raise ValueError("Ручной посев доступен только для knockout")
    if tournament.bracket_size is None:
        raise ValueError("У этого розыгрыша не задан размер сетки")
    expected_pairs = tournament.bracket_size // 2
    if len(pairs) != expected_pairs:
        raise ValueError(f"Нужно указать ровно {expected_pairs} пар для сетки на {tournament.bracket_size} участников")
    if await crud.list_playoff_matches(session, tournament.id):
        raise ValueError("Сетка для этого розыгрыша уже создана")

    valid_ids = {e.id for e in await crud.list_entries(session, tournament.id)}
    seen: set[int] = set()
    for entry_a, entry_b in pairs:
        if entry_a not in valid_ids or entry_b not in valid_ids:
            raise ValueError("В парах указан участник, не подключённый к этому розыгрышу")
        if entry_a == entry_b:
            raise ValueError("Участник не может играть сам с собой")
        for entry_id in (entry_a, entry_b):
            if entry_id in seen:
                raise ValueError("Каждый участник должен встречаться в сетке ровно один раз")
            seen.add(entry_id)

    matches = await _create_round(
        session, tournament.id, round_number=1, pairs=pairs, scheduled_date=tournament.start_date
    )

    tournament.status = TournamentStatus.playoff
    session.add(tournament)
    await session.commit()
    return matches


async def _create_round(
    session: AsyncSession, tournament_id: int, round_number: int, pairs: list[tuple[int, int]], scheduled_date
) -> list[PlayoffMatch]:
    matches = []
    for position, (entry_a, entry_b) in enumerate(pairs):
        matches.append(
            await crud.create_playoff_match(
                session, tournament_id, round_number, position, entry_a, entry_b, scheduled_date
            )
        )
    return matches


async def get_bracket_view(session: AsyncSession, tournament_id: int) -> list[dict]:
    """Список пар сетки с позывными — для админ-панели."""
    matches = await crud.list_playoff_matches(session, tournament_id)
    entry_by_id = {e.id: e for e in await crud.list_entries(session, tournament_id)}

    def callsign(entry_id: int | None) -> str | None:
        entry = entry_by_id.get(entry_id) if entry_id is not None else None
        return entry.callsign if entry else None

    return [
        {
            "id": m.id,
            "round_number": m.round_number,
            "position": m.position,
            "entry_a_id": m.entry_a_id,
            "entry_a_callsign": callsign(m.entry_a_id),
            "entry_b_id": m.entry_b_id,
            "entry_b_callsign": callsign(m.entry_b_id),
            "winner_entry_id": m.winner_entry_id,
            "status": m.status,
            "scheduled_date": m.scheduled_date,
        }
        for m in matches
    ]
