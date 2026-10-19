"""
Режим «Марафон»: игрок разгадывает несколько слов подряд. Админ задаёт число
слов (Tournament.words_count); слова хранятся как DailyWord (day_number =
номер слова по порядку), партии — как Attempt, так что замена слов, подсчёт
попыток и защита от дублей работают на готовых механизмах.

Каждый игрок идёт в своём темпе: следующее слово открывается, когда он
отгадал текущее или исчерпал 6 попыток. Место определяется числом попыток:
больше пройденных слов — выше; при равенстве — меньше суммарных попыток
(неугаданное слово считается за UNSOLVED_ATTEMPTS попыток); при полном
совпадении игроки делят место.
"""
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, Attempt, DailyWord, DailyWordStatus
from api.dictionary import pick_word_for_day
from api.tournament_time import today
from api import crud

MAX_ATTEMPTS = 6
UNSOLVED_ATTEMPTS = 7  # неугаданное слово в зачёте = 7 попыток
MIN_WORDS = 2
MAX_WORDS = 30


def attempt_finished(attempt: Attempt | None) -> bool:
    """Слово пройдено: угадано или исчерпаны все попытки."""
    return attempt is not None and (attempt.solved or attempt.attempts_used >= MAX_ATTEMPTS)


def counted_attempts(attempt: Attempt) -> int:
    """Сколько попыток засчитывается за слово в итоговой сумме."""
    return attempt.attempts_used if attempt.solved else UNSOLVED_ATTEMPTS


def is_open(tournament: Tournament) -> bool:
    """Идёт ли сейчас игра: дата старта наступила и дата окончания (если есть) не прошла."""
    if today() < tournament.start_date:
        return False
    if tournament.end_date is not None and today() > tournament.end_date:
        return False
    return True


def has_ended(tournament: Tournament) -> bool:
    return tournament.end_date is not None and today() > tournament.end_date


async def ensure_words(session: AsyncSession, tournament: Tournament) -> list[DailyWord]:
    """Гарантирует, что слова 1..words_count созданы (предложены системой), и
    возвращает их по порядку. Лишние слова (после уменьшения числа слов) не
    возвращаются — их удаляет admin при изменении настроек."""
    existing = {dw.day_number: dw for dw in await crud.list_daily_words(session, tournament.id)}
    created = False
    for number in range(1, (tournament.words_count or 0) + 1):
        if number in existing:
            continue
        already_used = await crud._get_used_words(session, tournament.id)
        word = pick_word_for_day(tournament.id, number, already_used)
        dw = DailyWord(
            tournament_id=tournament.id, day_number=number, word=word,
            calendar_date=tournament.start_date, status=DailyWordStatus.suggested,
        )
        session.add(dw)
        await session.commit()  # слово сразу «занято» для выбора следующих
        existing[number] = dw
        created = True
    if created:
        for dw in existing.values():
            await session.refresh(dw)
    return [existing[n] for n in range(1, (tournament.words_count or 0) + 1)]


@dataclass
class Progress:
    words: list[DailyWord]
    attempts: dict[int, Attempt]  # day_number -> попытка игрока
    current: DailyWord | None = None  # текущее слово (None — все пройдены)
    finished: list[tuple[DailyWord, Attempt]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.words)

    @property
    def done(self) -> bool:
        return self.current is None

    @property
    def current_index(self) -> int:
        return self.current.day_number if self.current is not None else self.total

    @property
    def total_attempts(self) -> int:
        return sum(counted_attempts(a) for _, a in self.finished)


async def get_progress(session: AsyncSession, tournament: Tournament, entry_id: int) -> Progress:
    words = await ensure_words(session, tournament)
    by_word = {}
    for dw in words:
        attempt = await crud.get_attempt(session, entry_id, dw.id)
        if attempt is not None:
            by_word[dw.day_number] = attempt
    progress = Progress(words=words, attempts=by_word)
    for dw in words:
        attempt = by_word.get(dw.day_number)
        if attempt_finished(attempt):
            progress.finished.append((dw, attempt))
        else:
            progress.current = dw
            break
    return progress


async def word_started(session: AsyncSession, daily_word_id: int) -> bool:
    """Начал ли хоть кто-то отгадывать это слово (есть строка Attempt)."""
    return await crud.daily_word_has_attempts(session, daily_word_id)


async def compute_standings(session: AsyncSession, tournament: Tournament) -> dict:
    """Сводная таблица для админки: по строке на игрока, ячейка на каждое слово."""
    words = await ensure_words(session, tournament)
    entries = [e for e in await crud.list_entries(session, tournament.id) if not e.hidden_from_standings]
    attempts = await crud.list_attempts_for_tournament(session, tournament.id)
    word_by_id = {dw.id: dw for dw in words}
    by_entry: dict[int, dict[int, Attempt]] = {}
    for a in attempts:
        dw = word_by_id.get(a.daily_word_id)
        if dw is not None:
            by_entry.setdefault(a.entry_id, {})[dw.day_number] = a

    rows = []
    for entry in entries:
        entry_attempts = by_entry.get(entry.id)
        if not entry_attempts:
            continue  # ещё не начинал — в таблице пока нет (как в стандартном режиме)
        cells = []
        words_done = 0
        total = 0
        for dw in words:
            attempt = entry_attempts.get(dw.day_number)
            if attempt_finished(attempt):
                words_done += 1
                total += counted_attempts(attempt)
                cells.append({"attempts_used": attempt.attempts_used, "solved": bool(attempt.solved), "finished": True})
            elif attempt is not None:
                cells.append({"attempts_used": attempt.attempts_used, "solved": False, "finished": False})
            else:
                cells.append(None)
        rows.append({
            "entry_id": entry.id, "callsign": entry.callsign, "cells": cells,
            "words_done": words_done, "total_attempts": total,
            "finished_all": words_done == len(words) and len(words) > 0,
        })

    rows.sort(key=lambda r: (-r["words_done"], r["total_attempts"], r["callsign"].lower()))
    # места: по (пройдено слов, сумма попыток); полное совпадение — общее место "2-3"
    i = 0
    while i < len(rows):
        j = i
        key = (rows[i]["words_done"], rows[i]["total_attempts"])
        while j + 1 < len(rows) and (rows[j + 1]["words_done"], rows[j + 1]["total_attempts"]) == key:
            j += 1
        place = str(i + 1) if i == j else f"{i + 1}-{j + 1}"
        for k in range(i, j + 1):
            rows[k]["place"] = place
        i = j + 1

    return {
        "words_count": len(words),
        "words": [{"day_number": dw.day_number, "word": dw.word} for dw in words],
        "unsolved_attempts": UNSOLVED_ATTEMPTS,
        "hashtag": tournament.hashtag,
        "rows": rows,
    }


async def words_overview(session: AsyncSession, tournament: Tournament) -> list[dict]:
    """Слова марафона для админки: само слово, сколько участников его начали и
    закончили; редактируемо, пока его никто не начал."""
    words = await ensure_words(session, tournament)
    started: dict[int, int] = {}
    finished: dict[int, int] = {}
    for a in await crud.list_attempts_for_tournament(session, tournament.id):
        started[a.daily_word_id] = started.get(a.daily_word_id, 0) + 1
        if attempt_finished(a):
            finished[a.daily_word_id] = finished.get(a.daily_word_id, 0) + 1
    return [
        {
            "id": dw.id, "day_number": dw.day_number, "word": dw.word, "status": dw.status.value,
            "started": started.get(dw.id, 0), "finished": finished.get(dw.id, 0),
            "editable": started.get(dw.id, 0) == 0,
        }
        for dw in words
    ]
