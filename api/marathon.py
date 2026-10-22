"""
Режим «Марафон»: игрок разгадывает несколько слов подряд. Админ задаёт число
слов (Tournament.words_count); слова хранятся как DailyWord (day_number =
номер слова по порядку), партии — как Attempt, так что замена слов, подсчёт
попыток и защита от дублей работают на готовых механизмах.

Слова бывают общими (одни и те же у всех, DailyWord.entry_id = NULL) или
личными (Tournament.individual_words: у каждого участника свой набор,
DailyWord.entry_id = участник). Автоматически подобранные слова не повторяются
между участниками; админ при ручной замене может повторить слово другого
участника (внутри одного набора повторы по-прежнему запрещены).

Каждый игрок идёт в своём темпе: следующее слово открывается, когда он
отгадал текущее или исчерпал 6 попыток. Место определяется числом попыток:
больше пройденных слов — выше; при равенстве — меньше суммарных попыток
(неугаданное слово считается за UNSOLVED_ATTEMPTS попыток); при полном
совпадении игроки делят место.
"""
from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, Attempt, DailyWord, DailyWordStatus
from api.dictionary import pick_word_for_day, pick_word_for_label, pick_alternative_word
from api.word_plan import marathon_length
from api.tournament_time import today
from api import crud

MAX_ATTEMPTS = 6
UNSOLVED_ATTEMPTS = 7  # неугаданное слово в зачёте = 7 попыток
MIN_WORDS = 2
MAX_WORDS = 30


class NotEnoughWords(Exception):
    """В словаре не хватает слов для нового набора (игроков × слов больше пула)."""


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


async def ensure_words(session: AsyncSession, tournament: Tournament, entry_id: int | None = None) -> list[DailyWord]:
    """Гарантирует, что слова 1..words_count созданы (предложены системой), и
    возвращает их по порядку. В режиме личных наборов нужен entry_id участника —
    возвращается его собственный набор; иначе — общий. Лишние слова (после
    уменьшения числа слов) не возвращаются — их удаляет admin при изменении
    настроек."""
    individual = bool(tournament.individual_words)
    if individual and entry_id is None:
        raise ValueError("В режиме личных наборов слов нужен участник")
    scope = entry_id if individual else None
    existing = {dw.day_number: dw for dw in await crud.list_marathon_words(session, tournament.id, scope)}
    created = False
    for number in range(1, (tournament.words_count or 0) + 1):
        if number in existing:
            continue
        already_used = await crud._get_used_words(session, tournament.id)  # слова всех участников + исключённые
        length = marathon_length(tournament, number)  # длина слова этой позиции по плану
        try:
            if individual:
                word = pick_word_for_label(f"marathon:{tournament.id}:{scope}:{number}", already_used, length)
            else:
                word = pick_word_for_day(tournament.id, number, already_used, length)
        except RuntimeError:
            raise NotEnoughWords(
                "В словаре не хватает слов для личных наборов: уменьшите число слов или число участников"
            )
        dw = DailyWord(
            tournament_id=tournament.id, entry_id=scope, day_number=number, word=word,
            calendar_date=tournament.start_date, status=DailyWordStatus.suggested,
        )
        session.add(dw)
        try:
            await session.commit()  # слово сразу «занято» для выбора следующих
        except IntegrityError:
            # параллельный запрос успел создать это же слово — берём то, что в базе
            await session.rollback()
            existing = {d.day_number: d for d in await crud.list_marathon_words(session, tournament.id, scope)}
            continue
        existing[number] = dw
        created = True
    if created:
        for dw in existing.values():
            await session.refresh(dw)
    return [existing[n] for n in range(1, (tournament.words_count or 0) + 1) if n in existing]


async def ensure_all(session: AsyncSession, tournament: Tournament) -> None:
    """Создаёт недостающие слова: общий набор либо личные наборы всех подключённых участников."""
    if not tournament.individual_words:
        await ensure_words(session, tournament)
        return
    for entry in await crud.list_entries(session, tournament.id):
        if entry.active:
            await ensure_words(session, tournament, entry.id)


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
    words = await ensure_words(session, tournament, entry_id)
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


async def compute_standings(
    session: AsyncSession, tournament: Tournament, apply_tie_resolutions: bool = True
) -> dict:
    """Сводная таблица для админки: по строке на игрока, ячейка на каждое слово.

    Порядок мест, заданный админом по итогам тай-брейка (tournament.tie_resolutions,
    «Разобрать ничьи»), применяется к группам с общим местом — только если состав
    группы в точности совпадает с сохранённым (устаревший порядок игнорируется).
    apply_tie_resolutions=False нужен, чтобы увидеть сами ничьи при их разборе."""
    individual = bool(tournament.individual_words)
    shared_words = [] if individual else await ensure_words(session, tournament)
    all_words = await crud.list_daily_words(session, tournament.id)
    words_by_entry: dict[int | None, list[DailyWord]] = {}
    for dw in all_words:
        if dw.day_number <= (tournament.words_count or 0):
            words_by_entry.setdefault(dw.entry_id, []).append(dw)
    for lst in words_by_entry.values():
        lst.sort(key=lambda d: d.day_number)

    entries = [e for e in await crud.list_entries(session, tournament.id) if not e.hidden_from_standings]
    attempts = await crud.list_attempts_for_tournament(session, tournament.id)
    by_entry: dict[int, dict[int, Attempt]] = {}
    for a in attempts:
        by_entry.setdefault(a.entry_id, {})[a.daily_word_id] = a

    count = tournament.words_count or 0
    rows = []
    for entry in entries:
        entry_attempts = by_entry.get(entry.id)
        if not entry_attempts:
            continue  # ещё не начинал — в таблице пока нет (как в стандартном режиме)
        words = shared_words if not individual else words_by_entry.get(entry.id, [])
        cells = []
        words_done = 0
        total = 0
        for number in range(1, count + 1):
            dw = next((w for w in words if w.day_number == number), None)
            attempt = entry_attempts.get(dw.id) if dw is not None else None
            word = dw.word if dw is not None else None
            if attempt_finished(attempt):
                words_done += 1
                total += counted_attempts(attempt)
                cells.append({
                    "attempts_used": attempt.attempts_used, "solved": bool(attempt.solved), "finished": True,
                    "word": word, "guesses": list(attempt.guesses),
                })
            elif attempt is not None:
                cells.append({
                    "attempts_used": attempt.attempts_used, "solved": False, "finished": False,
                    "word": word, "guesses": list(attempt.guesses),
                })
            else:
                cells.append(None)
        rows.append({
            "entry_id": entry.id, "callsign": entry.callsign, "cells": cells,
            "words_done": words_done, "total_attempts": total,
            "finished_all": words_done == count and count > 0,
        })

    rows.sort(key=lambda r: (-r["words_done"], r["total_attempts"], r["callsign"].lower()))
    resolution_by_set = (
        {frozenset(item["entry_ids"]): list(item["entry_ids"]) for item in (tournament.tie_resolutions or [])}
        if apply_tie_resolutions else {}
    )
    # места: по (пройдено слов, сумма попыток); полное совпадение — общее место "2-3",
    # если для группы не сохранён порядок по итогам тай-брейка (тогда места 2 и 3, со звёздочкой)
    i = 0
    while i < len(rows):
        j = i
        key = (rows[i]["words_done"], rows[i]["total_attempts"])
        while j + 1 < len(rows) and (rows[j + 1]["words_done"], rows[j + 1]["total_attempts"]) == key:
            j += 1
        place = str(i + 1) if i == j else f"{i + 1}-{j + 1}"
        group = rows[i:j + 1]
        order = resolution_by_set.get(frozenset(r["entry_id"] for r in group)) if j > i else None
        if order is not None:
            by_id = {r["entry_id"]: r for r in group}
            group = [by_id[entry_id] for entry_id in order]
            rows[i:j + 1] = group
        for offset, row in enumerate(group):
            row["place"] = str(i + 1 + offset) if order is not None else place
            row["tie_resolved"] = order is not None
        i = j + 1

    return {
        "words_count": count,
        # общий набор: слова в заголовках таблицы; личные наборы — только номера (слово у каждого своё)
        "words": [{"day_number": w.day_number, "word": w.word} for w in shared_words]
        if not individual else [{"day_number": n, "word": None} for n in range(1, count + 1)],
        "unsolved_attempts": UNSOLVED_ATTEMPTS,
        "hashtag": tournament.hashtag,
        "rows": rows,
    }


async def words_overview(session: AsyncSession, tournament: Tournament) -> list[dict]:
    """Общие слова марафона для админки: само слово, сколько участников его начали и
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
            "editable": started.get(dw.id, 0) == 0, "length": len(dw.word),
        }
        for dw in words
    ]


async def individual_overview(session: AsyncSession, tournament: Tournament) -> list[dict]:
    """Личные наборы всех подключённых участников для админки (недостающие слова
    создаются)."""
    attempts_by_word = {a.daily_word_id: a for a in await crud.list_attempts_for_tournament(session, tournament.id)}
    players = []
    for entry in await crud.list_entries(session, tournament.id):
        if not entry.active:
            continue
        items = []
        for dw in await ensure_words(session, tournament, entry.id):
            attempt = attempts_by_word.get(dw.id)
            state = "finished" if attempt_finished(attempt) else "started" if attempt is not None else "new"
            items.append({
                "id": dw.id, "day_number": dw.day_number, "word": dw.word, "status": dw.status.value,
                "state": state, "editable": attempt is None, "length": len(dw.word),
                "guesses": list(attempt.guesses) if attempt is not None else [],
            })
        players.append({"entry_id": entry.id, "callsign": entry.callsign, "words": items})
    return players


async def regenerate_entry_words(session: AsyncSession, tournament: Tournament, entry_id: int) -> int:
    """Заново подбирает все ещё не начатые слова личного набора участника; возвращает,
    сколько слов заменено."""
    words = await ensure_words(session, tournament, entry_id)
    used = await crud._get_used_words(session, tournament.id)
    replaced = 0
    for dw in words:
        if await crud.daily_word_has_attempts(session, dw.id):
            continue
        try:
            new_word = pick_alternative_word(used, exclude=dw.word, length=len(dw.word))  # длина позиции сохраняется
        except RuntimeError:
            raise NotEnoughWords("В словаре не хватает слов, чтобы подобрать новые")
        used.add(new_word)
        dw.word = new_word
        dw.status = DailyWordStatus.suggested
        session.add(dw)
        replaced += 1
    await session.commit()
    return replaced


async def regenerate_all(session: AsyncSession, tournament: Tournament) -> int:
    total = 0
    for entry in await crud.list_entries(session, tournament.id):
        if entry.active:
            total += await regenerate_entry_words(session, tournament, entry.id)
    return total


async def convert_mode(session: AsyncSession, tournament: Tournament, individual: bool) -> None:
    """Переключение «общие слова ↔ личные наборы». Только пока никто не начал играть:
    все слова удаляются и создаются заново в новом режиме."""
    if await crud.list_attempts_for_tournament(session, tournament.id):
        raise ValueError("Режим слов можно менять, только пока никто не сделал ни одной догадки")
    for dw in await crud.list_daily_words(session, tournament.id):
        await session.delete(dw)
    tournament.individual_words = individual
    session.add(tournament)
    await session.commit()
    if not individual:
        await ensure_words(session, tournament)


async def apply_lengths(session: AsyncSession, tournament: Tournament) -> int:
    """Подгоняет под план длин (word_plan["marathon"]) все ещё не начатые слова,
    предложенные системой: слово позиции, длина которого не совпадает с планом,
    заменяется новым нужной длины. Слова, подтверждённые или введённые админом
    вручную (статус confirmed), не трогаются — ручное слово главнее плана.
    Возвращает, сколько слов заменено."""
    used = await crud._get_used_words(session, tournament.id)
    replaced = 0
    for dw in await crud.list_daily_words(session, tournament.id):
        if dw.day_number > (tournament.words_count or 0) or dw.status != DailyWordStatus.suggested:
            continue
        wanted = marathon_length(tournament, dw.day_number)
        if len(dw.word) == wanted or await crud.daily_word_has_attempts(session, dw.id):
            continue
        try:
            new_word = pick_alternative_word(used, exclude=dw.word, length=wanted)
        except RuntimeError:
            raise NotEnoughWords("В словаре не хватает слов нужной длины")
        used.add(new_word)
        dw.word = new_word
        session.add(dw)
        replaced += 1
    await session.commit()
    return replaced
