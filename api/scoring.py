"""
Чистая логика подсчёта очков, мест и таблицы по дням — без обращений к БД,
чтобы было легко тестировать и переиспользовать (и в API, и при генерации
изображения таблицы, и в тестах).
"""
from dataclasses import dataclass, field


def calculate_points(attempts_used: int | None, solved: bool, scoring_rules: dict) -> int:
    """
    attempts_used: число использованных попыток (1..6), либо None если участник
    не играл в этот день (это отдельно обрабатывается как пропуск, а не как 0 очков
    за игру — семантически разные вещи, хотя итоговое число очков одинаковое).
    scoring_rules: {"1": 10, "2": 5, "3": 4, "4": 3, "5": 2, "6": 1}
    """
    if not solved or attempts_used is None:
        return 0
    return int(scoring_rules.get(str(attempts_used), 0))


@dataclass
class ParticipantDayResult:
    participant_id: int
    callsign: str
    played: bool          # делал ли попытку в этот день
    points: int | None    # None означает "пропуск" (флаг), не 0
    admin_note: str | None = None  # заполнено, только если результат дня скорректирован админом вручную


@dataclass
class StandingsRow:
    participant_id: int
    callsign: str
    total_points: int
    place: str             # "1", "2-3" и т.п. — уже с учётом дележа мест
    daily: list[ParticipantDayResult] = field(default_factory=list)


def build_standings(
    participants: list[dict],       # [{"id":..,"callsign":..}]
    daily_results: dict[int, dict[int, ParticipantDayResult]],
    # daily_results[day_number][participant_id] = ParticipantDayResult
    total_days: int,
) -> list[StandingsRow]:
    """
    Строит итоговую таблицу: сумма очков по всем дням + список по дням (с флагами
    для пропущенных). Дни, где участник не играл (в т.ч. до регистрации), помечаются
    played=False, что рендерится как флаг, а не как 0.

    Места с учётом равенства очков: при равной сумме очков выше становится
    участник с меньшим числом пропусков (played=False дней) — это основной
    тай-брейк таблицы. Только при полном совпадении и очков, и пропусков
    участники делят место в формате "2-3" (диапазон), следующий участник
    получает место сразу после диапазона (competition ranking).
    """
    totals: dict[int, int] = {}
    skips: dict[int, int] = {}
    for p in participants:
        pid = p["id"]
        total = 0
        skip_count = 0
        for day in range(1, total_days + 1):
            result = daily_results.get(day, {}).get(pid)
            if result and result.played and result.points is not None:
                total += result.points
            else:
                skip_count += 1
        totals[pid] = total
        skips[pid] = skip_count

    # сортировка по убыванию очков, при равенстве — по возрастанию числа пропусков
    ordered = sorted(participants, key=lambda p: (-totals[p["id"]], skips[p["id"]]))

    # вычисление мест с дележом (competition ranking: 1,2,2,4) — делят место
    # только участники с одинаковыми и очками, и числом пропусков
    rows: list[StandingsRow] = []
    i = 0
    while i < len(ordered):
        j = i
        while (
            j + 1 < len(ordered)
            and totals[ordered[j + 1]["id"]] == totals[ordered[i]["id"]]
            and skips[ordered[j + 1]["id"]] == skips[ordered[i]["id"]]
        ):
            j += 1
        if i == j:
            place_label = str(i + 1)
        else:
            place_label = f"{i + 1}-{j + 1}"

        for k in range(i, j + 1):
            p = ordered[k]
            pid = p["id"]
            daily_list = []
            for day in range(1, total_days + 1):
                result = daily_results.get(day, {}).get(pid)
                if result is None:
                    daily_list.append(
                        ParticipantDayResult(pid, p["callsign"], played=False, points=None)
                    )
                else:
                    daily_list.append(result)
            rows.append(
                StandingsRow(
                    participant_id=pid,
                    callsign=p["callsign"],
                    total_points=totals[pid],
                    place=place_label,
                    daily=daily_list,
                )
            )
        i = j + 1

    return rows


def groups_needing_tiebreak(rows: list[StandingsRow], playoff_cutoff: int) -> list[list[StandingsRow]]:
    """
    Находит группы участников, которым нужен тай-брейк — то есть тех, кто делит
    место в таблице (row.place вида "2-3"), а значит уже совпал и по очкам,
    и по числу пропусков (см. build_standings):
    - любая группа с дележом места ВНУТРИ топ-N (нужна для правильного посева)
    - группа на границе топ-N (от которой зависит, кто попадает в плей-офф)

    playoff_cutoff — то самое N (например, 16).
    Возвращает список групп (каждая группа — список StandingsRow с одинаковым total_points).
    """
    groups: list[list[StandingsRow]] = []
    seen_places = set()
    for row in rows:
        if row.place in seen_places:
            continue
        seen_places.add(row.place)
        if "-" not in row.place:
            continue  # без дележа — тай-брейк не нужен
        group = [r for r in rows if r.place == row.place]
        # группа релевантна, если хотя бы один участник группы имеет ранг <= cutoff
        # (т.е. группа либо целиком внутри топ-N, либо пересекает границу)
        start_rank = int(row.place.split("-")[0])
        if start_rank <= playoff_cutoff:
            groups.append(group)
    return groups
