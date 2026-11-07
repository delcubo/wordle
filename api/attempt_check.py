"""
Окно админки «Проверка»: собирает всё, что есть в базе, чтобы оценить подозрительный результат
(обычно — слово угадано с первой попытки). Сервер ничего не решает: он отдаёт факты и пару
нейтральных подсказок (signals), а вывод делает админ.

Что учитывается:
  - вводил ли игрок это слово раньше — в любых розыгрышах и на любой попытке, не только в этом дне;
  - кто закончил это слово до него (проигравшие — уже видели ответ);
  - было ли это слово ответом в другом розыгрыше рядом по датам;
  - его обычные первые слова и частота «1/6» против остальных.
Времени от открытия страницы до первой догадки в базе нет: попытка заводится по первой догадке
(Attempt.started_at), поэтому сравниваем момент результата с публикацией слова и с другими игроками.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import crud
from api.models import Attempt, DailyWord, Tournament, TournamentEntry, TournamentType, User
from api.tournament_time import TOURNAMENT_TZ

MAX_ATTEMPTS = 6
LIST_LIMIT = 10        # сколько строк показывать в каждом списке деталей
OPENERS_SHOWN = 5
RATE_FACTOR = 3        # «1/6» у игрока заметно чаще, чем у остальных, — во столько раз
MIN_GAMES_FOR_RATE = 10


def _utc(dt: datetime | None) -> datetime | None:
    # наивный UTC (datetime.utcnow) -> aware
    return dt.replace(tzinfo=timezone.utc) if dt else None


def _iso(dt: datetime | None) -> str | None:
    return _utc(dt).isoformat() if dt else None


def _finished(a: Attempt) -> bool:
    return bool(a.solved) or (a.attempts_used or 0) >= MAX_ATTEMPTS


def _published_at(day: date) -> datetime:
    """Момент публикации слова дня — 00:01 по времени розыгрыша (см. api/tournament_time.py)."""
    return datetime.combine(day, time(0, 1), tzinfo=TOURNAMENT_TZ).astimezone(timezone.utc)


def _label(dw: DailyWord, tournament: Tournament) -> str:
    if dw.bonus_number:
        return f"бонус {dw.bonus_number}"
    if tournament.type == TournamentType.marathon:
        return f"слово {dw.day_number}"
    return f"день {dw.day_number}"


def _pct(part: int, total: int) -> str:
    return f"{part / total * 100:.1f}%".replace(".", ",") if total else "—"


def _plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def _times(n: int) -> str:
    return f"{n} {_plural(n, 'раз', 'раза', 'раз')}"


async def _first_try_stats(session: AsyncSession, user_id: int | None = None) -> tuple[int, int]:
    """(закончено игр, из них угадано с первой попытки) — без результатов, выставленных админом вручную."""
    finished = (Attempt.solved.is_(True)) | (Attempt.attempts_used >= MAX_ATTEMPTS)
    q = select(
        func.count(Attempt.id),
        func.sum(case((and_(Attempt.solved.is_(True), Attempt.attempts_used == 1), 1), else_=0)),
    ).where(finished, Attempt.admin_note.is_(None))
    if user_id is not None:
        q = q.join(TournamentEntry, TournamentEntry.id == Attempt.entry_id).where(TournamentEntry.user_id == user_id)
    games, first = (await session.execute(q)).one()
    return int(games or 0), int(first or 0)


async def build_attempt_check(session: AsyncSession, entry: TournamentEntry, dw: DailyWord) -> dict:
    """Проверка результата участия entry по слову dw. ValueError — по этому слову у игрока нет попытки."""
    target = await crud.get_attempt(session, entry.id, dw.id)
    if target is None or not target.guesses and not target.attempts_used:
        raise ValueError("По этому слову у игрока нет попытки")
    tournament = await crud.get_tournament(session, dw.tournament_id)
    user = await session.get(User, entry.user_id)
    word = dw.word.lower()
    target_finished_at = target.finished_at

    # ---- вся история игрока: все его попытки во всех розыгрышах
    rows = (await session.execute(
        select(Attempt, DailyWord, Tournament)
        .join(DailyWord, Attempt.daily_word_id == DailyWord.id)
        .join(Tournament, DailyWord.tournament_id == Tournament.id)
        .join(TournamentEntry, Attempt.entry_id == TournamentEntry.id)
        .where(TournamentEntry.user_id == entry.user_id, Attempt.id != target.id)
    )).all()
    history, openers = [], Counter()
    for a, adw, t in rows:
        guesses = [g.lower() for g in (a.guesses or [])]
        if guesses:
            openers[guesses[0]] += 1
        if word in guesses:
            history.append({
                "tournament": t.title, "label": _label(adw, t), "date": adw.calendar_date.isoformat(),
                "position": guesses.index(word) + 1, "was_answer": adw.word.lower() == word,
                # в тот же календарный день (другой розыгрыш) «раньше» — по времени первой догадки
                "earlier": adw.calendar_date < dw.calendar_date or (
                    adw.calendar_date == dw.calendar_date and a.started_at is not None and target.started_at is not None
                    and a.started_at < target.started_at
                ),
            })
    history.sort(key=lambda h: h["date"])
    earlier = [h for h in history if h["earlier"]]
    earlier_first = [h for h in earlier if h["position"] == 1]
    games_with_guesses = sum(openers.values())

    # ---- кто закончил это слово раньше (проигравшие уже видели ответ)
    others = (await session.execute(
        select(Attempt, TournamentEntry.callsign)
        .join(TournamentEntry, TournamentEntry.id == Attempt.entry_id)
        .where(Attempt.daily_word_id == dw.id, Attempt.id != target.id, Attempt.finished_at.is_not(None))
    )).all()
    finishers = [(a, c) for a, c in others if _finished(a) and not a.admin_note]
    before = sorted(
        ((a, c) for a, c in finishers if target_finished_at is not None and a.finished_at < target_finished_at),
        key=lambda x: x[0].finished_at,
    )
    failed_before = [(a, c) for a, c in before if not a.solved]
    solved_before = [(a, c) for a, c in before if a.solved]

    # ---- это же слово как ответ в других розыгрышах рядом по датам
    near = (await session.execute(
        select(DailyWord, Tournament)
        .join(Tournament, DailyWord.tournament_id == Tournament.id)
        .where(
            func.lower(DailyWord.word) == word, DailyWord.id != dw.id,
            DailyWord.calendar_date >= dw.calendar_date - timedelta(days=1),
            DailyWord.calendar_date <= dw.calendar_date + timedelta(days=1),
        )
    )).all()
    other_tournaments = []
    for odw, ot in near:
        other = await crud.get_entry(session, ot.id, entry.user_id)
        oattempt = await crud.get_attempt(session, other.id, odw.id) if other is not None else None
        played_before = bool(
            oattempt is not None and _finished(oattempt) and oattempt.finished_at is not None
            and target_finished_at is not None and oattempt.finished_at < target_finished_at
        )
        other_tournaments.append({
            "tournament": ot.title, "label": _label(odw, ot), "date": odw.calendar_date.isoformat(),
            "played": oattempt is not None,
            "result": (f"{oattempt.attempts_used}/6" if oattempt.solved else "X/6") if oattempt is not None and _finished(oattempt) else None,
            "finished_before": played_before,
        })

    # ---- статистика «1/6»
    all_games, all_first = await _first_try_stats(session)
    my_games, my_first = await _first_try_stats(session, entry.user_id)
    rest_games, rest_first = all_games - my_games, all_first - my_first

    # ---- сам результат
    guessed_in = target.attempts_used if target.solved else None
    published = _published_at(dw.calendar_date)
    seconds_after_publish = (
        int((_utc(target_finished_at) - published).total_seconds()) if target_finished_at is not None else None
    )

    # ---- подсказки: нейтральные факты, итог решает админ
    signals = []
    if earlier_first:
        last = earlier_first[-1]
        signals.append({"tone": "ok", "text": (
            f"Это слово игрок уже вводил первой попыткой раньше — {_times(len(earlier_first))} "
            f"(последний раз: «{last['tournament']}», {last['label']}, {last['date'][8:10]}.{last['date'][5:7]})."
        )})
    elif earlier:
        signals.append({"tone": "info", "text": (
            f"Слово игрок вводил раньше, но не первой попыткой — в {_times(len(earlier))}."
        )})
    else:
        signals.append({"tone": "warn", "text": "До этого дня игрок это слово не вводил ни разу — ни первой, ни другой попыткой."})
    later = [h for h in history if not h["earlier"]]
    if later:
        signals.append({"tone": "info", "text": f"После этого дня вводил это слово ещё {_times(len(later))}."})

    if target.solved and target_finished_at is not None:
        if failed_before:
            signals.append({"tone": "warn", "text": (
                f"К моменту результата слово уже видели {len(failed_before)} "
                f"{_plural(len(failed_before), 'игрок', 'игрока', 'игроков')}, не угадавших его раньше "
                f"({', '.join(c for _, c in failed_before[:5])}{'…' if len(failed_before) > 5 else ''})."
            )})
        elif not before:
            signals.append({"tone": "ok", "text": "Игрок закончил первым — до него слово никто не заканчивал, подсказать результатами было некому."})
        else:
            signals.append({"tone": "ok", "text": f"До него слово не проиграл никто ({len(solved_before)} угадали): ответ ещё не был раскрыт."})

    for o in other_tournaments:
        if o["finished_before"]:
            signals.append({"tone": "warn", "text": (
                f"Это же слово было ответом в «{o['tournament']}» ({o['label']}, {o['date'][8:10]}.{o['date'][5:7]}) — "
                f"игрок закончил его там раньше ({o['result']})."
            )})

    if my_games:
        rate_text = f"1/6 у игрока: {my_first} из {my_games} ({_pct(my_first, my_games)}); у остальных — {rest_first} из {rest_games} ({_pct(rest_first, rest_games)})."
        often = (
            my_games >= MIN_GAMES_FOR_RATE and my_first >= 2 and rest_games > 0
            and my_first / my_games >= RATE_FACTOR * max(rest_first / rest_games, 0.001)
        )
        signals.append({"tone": "warn" if often else "info", "text": rate_text + (" У игрока заметно чаще." if often else "")})

    return {
        "entry_id": entry.id, "callsign": entry.callsign, "player_note": user.admin_note if user else None,
        "tournament": tournament.title, "day_label": _label(dw, tournament), "date": dw.calendar_date.isoformat(),
        "word": dw.word, "guesses": list(target.guesses or []), "attempts_used": target.attempts_used,
        "solved": bool(target.solved), "guessed_in": guessed_in,
        "manual": bool(target.admin_note),
        "finished_at": _iso(target_finished_at), "published_at": published.isoformat(),
        "seconds_after_publish": seconds_after_publish,
        "rank": len(before) + 1 if target_finished_at is not None else None, "finished_total": len(finishers) + 1,
        "signals": signals,
        "history": history[-LIST_LIMIT:], "history_total": len(history),
        "openers": [{"word": w, "count": n} for w, n in openers.most_common(OPENERS_SHOWN)],
        "openers_games": games_with_guesses,
        "failed_before": [{"callsign": c, "at": _iso(a.finished_at)} for a, c in failed_before[:LIST_LIMIT]],
        "solved_before": len(solved_before),
        "other_tournaments": other_tournaments[:LIST_LIMIT],
        "stats": {"player_games": my_games, "player_first": my_first, "rest_games": rest_games, "rest_first": rest_first},
    }
