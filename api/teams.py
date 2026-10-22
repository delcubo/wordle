"""
Командный зачёт марафона. Игроков в команды объединяет админ (TournamentEntry.team_id);
сама игра не меняется — меняется только таблица результатов.

Балл команды — среднее число попыток на слово по всем её участникам:

    (попытки по пройденным словам + UNSOLVED_ATTEMPTS * каждое непройденное слово)
        / (число участников * число слов марафона)

Непройденное слово (в том числе ещё не начатое или начатое, но не законченное) считается
как неугаданное, поэтому «спящий» игрок команду не выручает, а в начале игры все команды
выглядят одинаково плохо — прогресс показывается рядом (words_done / words_total).
Меньше — лучше. Сравнение точное (Fraction), показ — 2 знака, а если у команд с разными
местами два знака совпали — столько знаков, чтобы увидеть первое отличие (format_averages).

В зачёт идут команды не меньше MIN_TEAM_SIZE участников (скрытые из таблицы игроки не
считаются); меньшие показываются отдельно. Состав можно менять в любой момент — таблица
считается на лету, сохранённый порядок при ничьей устаревает, если меняется состав группы.
"""
from collections import defaultdict
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Team, TournamentEntry, Tournament, TournamentType
from api import crud, marathon

MIN_TEAM_SIZE = 2
MAX_NAME_LENGTH = 100


async def list_teams(session: AsyncSession, tournament_id: int) -> list[Team]:
    result = await session.execute(select(Team).where(Team.tournament_id == tournament_id).order_by(Team.id))
    return list(result.scalars().all())


async def _members(session: AsyncSession, team_id: int) -> list[TournamentEntry]:
    result = await session.execute(select(TournamentEntry).where(TournamentEntry.team_id == team_id))
    return list(result.scalars().all())


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise ValueError("Название команды не может быть пустым")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Название команды — не длиннее {MAX_NAME_LENGTH} символов")
    return name


async def _check_name_free(session: AsyncSession, tournament_id: int, name: str, except_id: int | None = None) -> None:
    for team in await list_teams(session, tournament_id):
        if team.id != except_id and team.name.lower() == name.lower():
            raise ValueError("Команда с таким названием уже есть")


async def create_team(session: AsyncSession, tournament: Tournament, name: str) -> Team:
    if tournament.type != TournamentType.marathon:
        raise ValueError("Команды есть только в марафоне")
    name = _clean_name(name)
    await _check_name_free(session, tournament.id, name)
    team = Team(tournament_id=tournament.id, name=name)
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return team


async def rename_team(session: AsyncSession, team: Team, name: str) -> Team:
    name = _clean_name(name)
    await _check_name_free(session, team.tournament_id, name, except_id=team.id)
    team.name = name
    session.add(team)
    await session.commit()
    await session.refresh(team)
    return team


async def delete_team(session: AsyncSession, team: Team) -> None:
    """Удаляет команду; её участники остаются в розыгрыше без команды."""
    for entry in await _members(session, team.id):
        entry.team_id = None
        session.add(entry)
    await session.delete(team)
    await session.commit()


async def assign_entry(session: AsyncSession, entry: TournamentEntry, team_id: int | None) -> TournamentEntry:
    """Поместить участника в команду (None — убрать из команды). Команда должна быть из того же розыгрыша."""
    if team_id is not None:
        team = await session.get(Team, team_id)
        if team is None or team.tournament_id != entry.tournament_id:
            raise ValueError("Команда не найдена в этом розыгрыше")
    entry.team_id = team_id
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def team_name_for_entry(session: AsyncSession, tournament: Tournament, entry: TournamentEntry) -> str | None:
    """Название команды игрока для отчёта — только если командный зачёт включён и игрок в команде."""
    if not tournament.teams_enabled or entry.team_id is None:
        return None
    team = await session.get(Team, entry.team_id)
    return team.name if team is not None and team.tournament_id == tournament.id else None


def _format(value: Fraction, digits: int) -> str:
    """Округление «половина вверх» до digits знаков без плавающей арифметики."""
    scaled = value * 10 ** digits
    n = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    text = str(n).rjust(digits + 1, "0")
    return f"{text[:-digits]}.{text[-digits:]}"


def format_averages(scores: list[Fraction]) -> list[str]:
    """Подписи средних: 2 знака; если у разных по значению команд два знака совпали —
    для этой группы берём столько знаков, чтобы все они различались (до первой
    отличающейся цифры). Одинаковые значения (ничья) остаются с одинаковой подписью."""
    base = [_format(s, 2) for s in scores]
    groups: dict[str, set[Fraction]] = defaultdict(set)
    for score, text in zip(scores, base):
        groups[text].add(score)
    digits_for: dict[str, int] = {}
    for text, distinct in groups.items():
        if len(distinct) < 2:
            continue
        digits = 3
        while digits < 15 and len({_format(s, digits) for s in distinct}) < len(distinct):
            digits += 1
        digits_for[text] = digits
    return [_format(s, digits_for[text]) if text in digits_for else text for s, text in zip(scores, base)]


async def compute_team_standings(
    session: AsyncSession, tournament: Tournament, apply_tie_resolutions: bool = True
) -> dict:
    """Командная таблица: rows — команды в зачёте (по возрастанию среднего), excluded —
    команды меньше MIN_TEAM_SIZE участников. Порядок мест, заданный админом при ничьей
    (tournament.team_tie_resolutions), применяется, если состав группы совпадает с
    сохранённым; apply_tie_resolutions=False нужен, чтобы увидеть сами ничьи."""
    data = await marathon.compute_standings(session, tournament, apply_tie_resolutions=False)
    count = data["words_count"]
    rows_by_entry = {r["entry_id"]: r for r in data["rows"]}  # только игравшие и не скрытые

    members_by_team: dict[int, list[TournamentEntry]] = defaultdict(list)
    for entry in await crud.list_entries(session, tournament.id):
        if entry.team_id is not None and not entry.hidden_from_standings:
            members_by_team[entry.team_id].append(entry)

    ranked: list[dict] = []
    excluded: list[dict] = []
    for team in await list_teams(session, tournament.id):
        members = sorted(members_by_team.get(team.id, []), key=lambda e: e.callsign.lower())
        member_rows = []
        attempts_sum = 0
        words_done = 0
        for entry in members:
            row = rows_by_entry.get(entry.id)
            done = row["words_done"] if row else 0
            attempts = row["total_attempts"] if row else 0
            attempts_sum += attempts
            words_done += done
            member_rows.append({
                "entry_id": entry.id, "callsign": entry.callsign, "words_done": done,
                "total_attempts": attempts, "finished_all": count > 0 and done == count, "active": entry.active,
            })
        size = len(members)
        item = {
            "team_id": team.id, "name": team.name, "members_count": size, "members": member_rows,
            "words_done": words_done, "words_total": size * count,
        }
        if size < MIN_TEAM_SIZE:
            excluded.append(item)
            continue
        unplayed = size * count - words_done
        item["attempts_sum"] = attempts_sum
        item["unplayed_words"] = unplayed
        item["score"] = Fraction(attempts_sum + marathon.UNSOLVED_ATTEMPTS * unplayed, size * count)
        ranked.append(item)

    ranked.sort(key=lambda t: (t["score"], t["name"].lower()))
    for item, text in zip(ranked, format_averages([t["score"] for t in ranked])):
        item["average"] = text
        item["average_value"] = float(item["score"])

    resolution_by_set = (
        {frozenset(item["team_ids"]): list(item["team_ids"]) for item in (tournament.team_tie_resolutions or [])}
        if apply_tie_resolutions else {}
    )
    i = 0
    while i < len(ranked):
        j = i
        while j + 1 < len(ranked) and ranked[j + 1]["score"] == ranked[i]["score"]:
            j += 1
        place = str(i + 1) if i == j else f"{i + 1}-{j + 1}"
        group = ranked[i:j + 1]
        order = resolution_by_set.get(frozenset(t["team_id"] for t in group)) if j > i else None
        if order is not None:
            by_id = {t["team_id"]: t for t in group}
            group = [by_id[team_id] for team_id in order]
            ranked[i:j + 1] = group
        for offset, item in enumerate(group):
            item["place"] = str(i + 1 + offset) if order is not None else place
            item["tie_resolved"] = order is not None
        i = j + 1

    for item in ranked:
        del item["score"]  # Fraction не сериализуется; для API есть average / average_value
    return {
        "words_count": count, "unsolved_attempts": marathon.UNSOLVED_ATTEMPTS,
        "hashtag": tournament.hashtag, "rows": ranked, "excluded": excluded,
    }


async def tie_groups(session: AsyncSession, tournament: Tournament) -> list[dict]:
    """Группы команд с общим местом (без учёта уже применённых порядков) + применённый порядок."""
    data = await compute_team_standings(session, tournament, apply_tie_resolutions=False)
    applied = {frozenset(r["team_ids"]): r for r in (tournament.team_tie_resolutions or [])}
    groups = []
    seen: set[str] = set()
    for row in data["rows"]:
        if "-" not in row["place"] or row["place"] in seen:
            continue
        seen.add(row["place"])
        members = [r for r in data["rows"] if r["place"] == row["place"]]
        current = applied.get(frozenset(m["team_id"] for m in members))
        groups.append({
            "place": row["place"],
            "summary": f"{row['average']} попыток на слово · {row['words_done']}/{row['words_total']} слов",
            "members": [{"team_id": m["team_id"], "name": m["name"]} for m in members],
            "applied_order": current["team_ids"] if current else None,
            "applied_source": (current.get("source") or None) if current else None,
        })
    return groups
