"""
Загрузка словаря и выбор слова дня.

Источник словаря: https://github.com/mediahope/Wordle-Russian-Dictionary
(открытый список 5-буквенных русских слов). Список содержит словоформы, включая
падежные формы — этого достаточно для проверки ВВОДИМЫХ попыток (в реальном Wordle
словарь допустимых слов всегда шире списка возможных ответов), но для более
"чистого" выбора слова дня в будущем имеет смысл сузить список ответов до
начальных форм существительных/прилагательных. TODO: curated answer list.
"""
import os
import random

_DICT_PATH = os.path.join(os.path.dirname(__file__), "data", "russian_words.txt")

_words_cache: list[str] | None = None
_words_set_cache: set[str] | None = None


def load_words() -> list[str]:
    global _words_cache
    if _words_cache is None:
        with open(_DICT_PATH, encoding="utf-8") as f:
            _words_cache = [line.strip() for line in f if line.strip()]
    return _words_cache


def is_valid_word(word: str) -> bool:
    """Проверка, что слово есть в словаре допустимых попыток."""
    global _words_set_cache
    if _words_set_cache is None:
        _words_set_cache = set(load_words())
    return word.lower() in _words_set_cache


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
        return "Такого слова нет в словаре"
    if word in already_used:
        return "Это слово уже использовалось в этом розыгрыше"
    return None
