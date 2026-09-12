"""
Загрузка словаря ответов и выбор слова дня.

Один и тот же отфильтрованный список (api/data/answer_words.txt) используется
и для выбора слова дня, и для проверки вводимых попыток — игрок может ввести
только то, что само могло бы оказаться загаданным словом (существительное в
именительном падеже, без словоформ, других частей речи, имён собственных).

Список получен из широкого исходного словаря (26 471 слово со всеми
словоформами, источник — https://github.com/mediahope/Wordle-Russian-Dictionary)
морфологическим анализом — см. scripts/build_answer_words.py и лежащий рядом
с ним исходник scripts/data/russian_words.txt, если понадобится пересобрать
список заново.
"""
import os
import random

_WORDS_PATH = os.path.join(os.path.dirname(__file__), "data", "answer_words.txt")
_EXTRA_WORDS_PATH = os.path.join(os.path.dirname(__file__), "data", "answer_words_extra.txt")

_words_cache: list[str] | None = None
_normalized_index_cache: dict[str, str] | None = None


def _read_word_list(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def load_words() -> list[str]:
    """
    Основной автособранный список (answer_words.txt) плюс ручные точечные
    дополнения (answer_words_extra.txt) — слова, которых не было в исходных
    26 471 и которые обнаружились по факту игры (см. пункт бэклога про
    неполноту словаря). Пересобирать answer_words.txt заново из-за одного
    найденного слова не нужно — достаточно дописать строку в extra-файл.
    """
    global _words_cache
    if _words_cache is None:
        _words_cache = _read_word_list(_WORDS_PATH) + _read_word_list(_EXTRA_WORDS_PATH)
    return _words_cache


def normalize_yo(word: str) -> str:
    """ё и е при вводе и сравнении считаются одной и той же буквой — почти
    никто не набирает ё намеренно, и с точки зрения игры это не должно считаться
    ошибкой (см. пункт бэклога про 'желоб'/'жёлоб')."""
    return word.replace("ё", "е")


def _normalized_index() -> dict[str, str]:
    """normalize_yo(слово) -> каноническое написание из словаря (то, что реально
    хранится и показывается игроку как ответ)."""
    global _normalized_index_cache
    if _normalized_index_cache is None:
        _normalized_index_cache = {normalize_yo(w): w for w in load_words()}
    return _normalized_index_cache


def register_added_word(word: str) -> None:
    """
    Добавляет слово, найденное отсутствующим по факту игры, в словарь этого
    процесса — сразу становится и валидной попыткой (is_valid_word), и
    кандидатом на слово дня (pick_word_for_day и т.п.). Источник правды —
    таблица AddedWord в БД (см. api/routers/admin.py); эта функция только
    обновляет кэш в памяти текущего процесса — при старте им же заполняется
    api/main.py из БД, а при добавлении через админку вызывается сразу же,
    без перезапуска. Не трогает файлы репозитория (в отличие от
    answer_words_extra.txt) — переживает только до следующего деплоя/рестарта
    процесса, для чего и нужна БД как источник правды.
    """
    words = load_words()  # гарантирует, что кэш уже инициализирован
    if word in words:
        return
    words.append(word)
    _normalized_index()[normalize_yo(word)] = word


def unregister_added_word(word: str) -> None:
    """Обратное действие — админ удалил ранее добавленное слово из панели."""
    words = load_words()
    if word in words:
        words.remove(word)
    normalized = _normalized_index()
    if normalized.get(normalize_yo(word)) == word:
        del normalized[normalize_yo(word)]


def is_valid_word(word: str) -> bool:
    """Проверка и вводимой попытки, и кандидата на слово дня — один и тот же список."""
    return normalize_yo(word.lower()) in _normalized_index()


def canonical_word(word: str) -> str | None:
    """Каноническое написание словарного слова (с ё, если оно у него есть) для
    введённого варианта (с е или ё) — None, если такого слова в словаре нет."""
    return _normalized_index().get(normalize_yo(word.lower()))


def pick_word_for_day(tournament_id: int, day_number: int, already_used: set[str]) -> str:
    """
    Детерминированный выбор слова дня: одинаковый tournament_id + day_number всегда
    дают одно и то же слово (не нужно хранить выбор заранее и он воспроизводим),
    но при этом слово не повторяется в рамках розыгрыша (already_used — уже
    использованные слова в этом розыгрыше, передаются из БД).
    """
    words = load_words()
    rng = random.Random(f"{tournament_id}:{day_number}")
    candidates = [w for w in words if w not in already_used]
    if not candidates:
        raise RuntimeError("Словарь исчерпан — слов для нового дня не осталось")
    return rng.choice(candidates)


def pick_word_for_match(match_id: int, game_number: int, already_used: set[str]) -> str:
    """
    Детерминированный выбор слова для конкретной игры внутри пары сетки —
    аналог pick_word_for_day, но сид строится из id пары и номера игры (у пар
    нет единого "номера дня розыгрыша", как у обычных дней).
    """
    words = load_words()
    rng = random.Random(f"match:{match_id}:{game_number}")
    candidates = [w for w in words if w not in already_used]
    if not candidates:
        raise RuntimeError("Словарь исчерпан — слов для новой игры сетки не осталось")
    return rng.choice(candidates)


def pick_alternative_word(already_used: set[str], exclude: str | None = None) -> str:
    """
    Выбор нового случайного предложения взамен текущего (кнопка "предложить
    другое слово" в админке) — в отличие от pick_word_for_day, недетерминирован:
    иначе повторное нажатие всегда возвращало бы то же самое слово.
    exclude — текущее предложенное слово, чтобы не предложить его же снова.
    """
    words = load_words()
    excluded = already_used | ({exclude} if exclude else set())
    candidates = [w for w in words if w not in excluded]
    if not candidates:
        raise RuntimeError("Словарь исчерпан — новых слов для замены не осталось")
    return random.choice(candidates)


def validate_manual_word(word: str, already_used: set[str]) -> str | None:
    """
    Проверка слова, которое администратор вводит вручную взамен предложенного.
    Возвращает текст ошибки (для показа в UI) или None, если всё в порядке.
    """
    word = word.lower().strip()
    if len(word) != 5:
        return "Слово должно быть из 5 букв"
    if not is_valid_word(word):
        return "Слово должно быть существительным в именительном падеже из словаря ответов"
    already_used_normalized = {normalize_yo(w) for w in already_used}
    if normalize_yo(word) in already_used_normalized:
        return "Это слово уже использовалось в этом розыгрыше"
    return None
