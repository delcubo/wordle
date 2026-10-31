"""
Экран админки «Сегодня»: по карточке на каждый идущий (или стартующий в ближайшие дни)
розыгрыш — сколько игроков уже закончили, с каким результатом, и слово на завтра, которое
можно подтвердить, не заходя в розыгрыш. Результаты считаются по режимам:
  - standard / endless / championship (основной этап) — сегодняшнее слово дня;
  - knockout / championship (плей-офф) — сегодняшние игры пар;
  - marathon — слова, пройденные каждым игроком;
  - tiebreak (и тай-брейк чемпионата) — текущие раунды.
Карточка — только чтение; слова меняются теми же эндпоинтами, что и на странице розыгрыша.
"""
from datetime import timezone

from sqlalchemy.ext.asyncio import AsyncSession

from api import crud, marathon
from api.models import Tournament, TournamentStatus, TournamentType
from api.tournament_time import today, day_number_for_date, effective_status

MAX_ATTEMPTS = 6
UPCOMING_DRAFT_DAYS = 3   # ещё не начавшийся розыгрыш показываем, если стартует не позже чем через столько дней
NO_DAILY_WORD = (TournamentType.knockout, TournamentType.tiebreak, TournamentType.marathon)


def _iso_utc(naive_dt) -> str | None:
    # наивный UTC (datetime.utcnow) -> ISO с явной зоной, иначе браузер прочитает как локальное время
    return naive_dt.replace(tzinfo=timezone.utc).isoformat() if naive_dt else None


def _finished(attempt) -> bool:
    return attempt is not None and (bool(attempt.solved) or (attempt.attempts_used or 0) >= MAX_ATTEMPTS)


def _attempt_text(attempt) -> str:
    return f"{attempt.attempts_used}/6" if attempt.solved else "X/6"


async def _daily_results(session: AsyncSession, tournament: Tournament, entries: list) -> tuple[list[dict], str]:
    """Результаты по слову сегодняшнего дня (standard/endless/championship в основном этапе)."""
    day = day_number_for_date(tournament.start_date, today())
    if day < 1 or (tournament.duration_days is not None and day > tournament.duration_days):
        return [], ""
    label = f"день {day} из {tournament.duration_days}" if tournament.duration_days else f"день {day}"
    word = await crud.get_daily_word_by_day(session, tournament.id, day)
    if word is None:
        return [], label
    results = []
    for e in entries:
        attempt = await crud.get_attempt(session, e.id, word.id)
        if attempt is None or not (attempt.guesses or attempt.attempts_used):
            continue
        done = _finished(attempt)
        results.append({
            "callsign": e.callsign, "done": done,
            "text": _attempt_text(attempt) if done else "играет",
            "at": _iso_utc(attempt.finished_at if done else attempt.started_at),
        })
    return results, label


async def _bracket_results(session: AsyncSession, tournament: Tournament, entries: list) -> tuple[list[dict], str, int]:
    """Сегодняшние игры пар: игрок «закончил», когда сыграл все сегодняшние игры своей пары.
    Возвращает (результаты, метка, сколько игроков сегодня вообще играет)."""
    by_id = {e.id: e for e in entries}
    results, playing = [], 0
    round_label = ""
    for match in await crud.list_playoff_matches(session, tournament.id):
        games = [g for g in await crud.list_playoff_games(session, match.id) if g.calendar_date == today()]
        if not games:
            continue
        round_label = "игра за 3 место" if match.is_third_place else f"раунд {match.round_number}"
        for side, entry_id in (("a", match.entry_a_id), ("b", match.entry_b_id)):
            if entry_id is None or entry_id not in by_id:
                continue
            playing += 1
            parts, done_all, started = [], True, False
            for g in games:
                used = getattr(g, f"entry_{side}_attempts_used")
                if getattr(g, f"entry_{side}_technical_loss"):
                    parts.append("пропуск")
                    started = True
                elif used is None:
                    done_all = False
                    started = started or bool(getattr(g, f"entry_{side}_guesses"))
                else:
                    parts.append(str(used) if getattr(g, f"entry_{side}_solved") else "X")
                    started = True
            if not started:
                continue
            text = (" · ".join(parts) + ("/6" if "пропуск" not in parts else "")) if parts else "играет"
            if not done_all:
                text = "играет" if not parts else f"{text} · играет"
            results.append({
                "callsign": by_id[entry_id].callsign, "done": done_all, "text": text,
                "at": _iso_utc(getattr(games[-1], f"entry_{side}_finished_at") if done_all else getattr(games[-1], f"entry_{side}_started_at")),
            })
    return results, round_label or "сегодня игр нет", playing


async def _marathon_results(session: AsyncSession, tournament: Tournament) -> list[dict]:
    standings = await marathon.compute_standings(session, tournament)
    count = standings["words_count"]
    results = []
    for row in standings["rows"]:
        done = row["finished_all"]
        results.append({
            "callsign": row["callsign"], "done": done, "at": None,
            "text": f"{row['words_done']}/{count} слов · {row['total_attempts']} поп." if not done else f"все слова · {row['score']} оч.",
        })
    return results


async def _tiebreak_results(session: AsyncSession, tournament: Tournament, entries: list) -> tuple[list[dict], str, int]:
    """Незавершённые раунды тай-брейка: у каждого участника своё слово (в командном — личное)."""
    by_id = {e.id: e for e in entries}
    results, playing, current = [], 0, None
    for r in await crud.list_tiebreak_rounds(session, tournament.id):
        if r.completed:
            continue
        current = r.round_number if current is None else max(current, r.round_number)
        for p in await crud.list_tiebreak_participants(session, r.id):
            if p.entry_id not in by_id:
                continue
            playing += 1
            attempt = await crud.get_attempt(session, p.entry_id, p.daily_word_id or r.daily_word_id)
            if attempt is None or not (attempt.guesses or attempt.attempts_used):
                continue
            done = _finished(attempt)
            results.append({
                "callsign": by_id[p.entry_id].callsign, "done": done,
                "text": _attempt_text(attempt) if done else "играет",
                "at": _iso_utc(attempt.finished_at if done else attempt.started_at),
            })
    return results, (f"раунд {current}" if current else "нет активных раундов"), playing


async def _upcoming_word(session: AsyncSession, tournament: Tournament) -> dict | None:
    """Слово на ближайший ещё не наступивший день — как GET /tournaments/{id}/words/upcoming."""
    if tournament.type in NO_DAILY_WORD:
        return None
    next_day = max(day_number_for_date(tournament.start_date, today()), 0) + 1
    if tournament.duration_days is not None and next_day > tournament.duration_days:
        return None
    word = await crud.get_or_suggest_daily_word(session, tournament, next_day)
    return {
        "id": word.id, "day_number": word.day_number, "calendar_date": word.calendar_date.isoformat(),
        "word": word.word, "length": len(word.word), "status": word.status.value if hasattr(word.status, "value") else word.status,
    }


async def build_today(session: AsyncSession) -> list[dict]:
    cards = []
    for t in await crud.list_tournaments(session):
        if t.archived:
            continue
        status = effective_status(t)
        if status == TournamentStatus.finished:
            continue
        if status == TournamentStatus.draft and (t.start_date - today()).days > UPCOMING_DRAFT_DAYS:
            continue

        entries = [e for e in await crud.list_entries(session, t.id) if e.active]
        results: list[dict] = []
        label, playing = "", len(entries)
        if status == TournamentStatus.draft:
            label = f"старт {t.start_date.strftime('%d.%m')}"
            playing = 0
        elif t.type == TournamentType.marathon:
            results = await _marathon_results(session, t)
            label = f"слов: {t.words_count}"
        elif t.type == TournamentType.knockout or status == TournamentStatus.playoff:
            results, label, playing = await _bracket_results(session, t, entries)
            if t.type == TournamentType.championship:
                label = f"плей-офф · {label}"  # у «На вылет» режим и так назван в карточке
        elif t.type == TournamentType.tiebreak or status == TournamentStatus.tiebreak:
            results, label, playing = await _tiebreak_results(session, t, entries)
            if t.type == TournamentType.championship:
                label = f"тай-брейк · {label}"
        else:
            results, label = await _daily_results(session, t, entries)

        done = sum(1 for r in results if r["done"])
        results.sort(key=lambda r: (not r["done"], r["at"] or "~", r["callsign"].lower()))
        attention = []
        if t.paused:
            attention.append("розыгрыш приостановлен")
        if not entries:
            attention.append("нет подключённых игроков")
        cards.append({
            "id": t.id, "title": t.title, "type": t.type.value, "status": status.value, "paused": bool(t.paused),
            "label": label, "players_total": playing, "done": done, "in_progress": len(results) - done,
            "results": results, "next_word": await _upcoming_word(session, t), "attention": attention,
        })
    return cards
