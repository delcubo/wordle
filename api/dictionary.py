"""
Загрузка словарей и выбор слова дня — для слов из 5, 6 и 7 букв.

Для каждой длины два списка:
  - ответы (load_words) — слова, которые система может загадать;
  - допустимые попытки (is_valid_word) — всё, что игрок может ввести; всегда
    включают ответы.

5 букв: ответы — api/data/answer_words.txt (+ ручные дополнения), допустимые
попытки — api/data/valid_5.txt (все существительные в начальной форме) плюс
ответы. 6 и 7 букв: api/data/answers_N.txt и api/data/valid_N.txt — см.
scripts/build_word_lists.py (сборка прямо из морфологического словаря). Ручные
дополнения (answer_words_extra.txt), слова из админки (таблица AddedWord) и
исключения (excluded_words.txt, ExcludedWord) общие для всех длин: слово
относится к своей длине по числу букв.

Исходный список ответов на 5 букв получен из широкого словаря (26 471 слово со
всеми словоформами, источник — https://github.com/mediahope/Wordle-Russian-Dictionary)
морфологическим анализом — см. scripts/build_answer_words.py и лежащий рядом с
ним исходник scripts/data/russian_words.txt.
"""
import hashlib
import os
import random

SUPPORTED_LENGTHS = (5, 6, 7)
DEFAULT_LENGTH = 5

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_WORDS_PATH = os.path.join(_DATA_DIR, "answer_words.txt")  # ответы на 5 букв
_EXTRA_WORDS_PATH = os.path.join(_DATA_DIR, "answer_words_extra.txt")
_EXCLUDED_WORDS_PATH = os.path.join(_DATA_DIR, "excluded_words.txt")

# длина -> список ответов
_words_cache: dict[int, list[str]] = {}
# длина -> {normalize_yo(слово): каноническое написание} по всем допустимым попыткам
_normalized_index_cache: dict[int, dict[str, str]] = {}
_file_excluded_cache: frozenset[str] | None = None


def _read_word_list(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def _check_length(length: int) -> int:
    if length not in SUPPORTED_LENGTHS:
        raise ValueError(f"Длина слова {length} не поддерживается (доступно: {SUPPORTED_LENGTHS})")
    return length


def load_words(length: int = DEFAULT_LENGTH) -> list[str]:
    """
    Список ответов для длины: основной автособранный список плюс ручные точечные
    дополнения (answer_words_extra.txt) — слова, которых не было в исходном
    словаре и которые обнаружились по факту игры. Пересобирать списки заново из-за
    одного найденного слова не нужно — достаточно дописать строку в extra-файл.
    """
    _check_length(length)
    if length not in _words_cache:
        base_path = _WORDS_PATH if length == 5 else os.path.join(_DATA_DIR, f"answers_{length}.txt")
        extra = [w for w in _read_word_list(_EXTRA_WORDS_PATH) if len(w) == length]
        _words_cache[length] = _read_word_list(base_path) + extra
    return _words_cache[length]


def load_file_excluded_words() -> frozenset[str]:
    """
    Слова, исключённые из выбора будущих слов дня файлом репозитория
    (excluded_words.txt) — в дополнение к тем, что админ исключил через панель
    (таблица ExcludedWord в БД). Файл переживает смену базы данных/хостинга.
    Написание приводится к каноническому из словаря (е/ё); слова, которых в
    словаре нет, остаются как есть. Влияет только на выбор будущих слов, как и
    исключения из БД — на проверку вводимых попыток не влияет.
    """
    global _file_excluded_cache
    if _file_excluded_cache is None:
        raw = _read_word_list(_EXCLUDED_WORDS_PATH) if os.path.exists(_EXCLUDED_WORDS_PATH) else []
        _file_excluded_cache = frozenset(canonical_word(w) or w for w in raw)
    return _file_excluded_cache


def normalize_yo(word: str) -> str:
    """ё и е при вводе и сравнении считаются одной и той же буквой — почти
    никто не набирает ё намеренно, и с точки зрения игры это не должно считаться
    ошибкой (см. пункт бэклога про 'желоб'/'жёлоб')."""
    return word.replace("ё", "е")


def _normalized_index(length: int = DEFAULT_LENGTH) -> dict[str, str]:
    """normalize_yo(слово) -> каноническое написание из словаря (то, что реально
    хранится и показывается игроку как ответ). Допустимые попытки: все
    существительные длины (valid_N.txt) плюс ответы — написание из ответов главнее."""
    _check_length(length)
    if length not in _normalized_index_cache:
        index: dict[str, str] = {}
        valid_path = os.path.join(_DATA_DIR, f"valid_{length}.txt")
        if os.path.exists(valid_path):
            for w in _read_word_list(valid_path):
                index[normalize_yo(w)] = w
        for w in load_words(length):
            index[normalize_yo(w)] = w
        _normalized_index_cache[length] = index
    return _normalized_index_cache[length]


def register_added_word(word: str) -> None:
    """
    Добавляет слово, найденное отсутствующим по факту игры, в словарь этого
    процесса — сразу становится и валидной попыткой (is_valid_word), и
    кандидатом на слово дня (pick_word_for_day и т.п.). Источник правды —
    таблица AddedWord в БД (см. api/routers/admin/dictionary.py); эта функция только
    обновляет кэш в памяти текущего процесса — при старте им же заполняется
    api/main.py из БД, а при добавлении через админку вызывается сразу же,
    без перезапуска. Не трогает файлы репозитория (в отличие от
    answer_words_extra.txt) — переживает только до следующего деплоя/рестарта
    процесса, для чего и нужна БД как источник правды. Длина — по самому слову.
    """
    if len(word) not in SUPPORTED_LENGTHS:
        return
    words = load_words(len(word))  # гарантирует, что кэш уже инициализирован
    if word in words:
        return
    words.append(word)
    _normalized_index(len(word))[normalize_yo(word)] = word


def unregister_added_word(word: str) -> None:
    """Обратное действие — админ удалил ранее добавленное слово из панели."""
    if len(word) not in SUPPORTED_LENGTHS:
        return
    words = load_words(len(word))
    if word in words:
        words.remove(word)
    normalized = _normalized_index(len(word))
    if normalized.get(normalize_yo(word)) == word:
        del normalized[normalize_yo(word)]


def is_valid_word(word: str, length: int | None = None) -> bool:
    """Допустимая попытка заданной длины (по умолчанию — по длине самого слова).
    Слово другой длины недопустимо."""
    w = normalize_yo(word.lower())
    length = len(w) if length is None else length
    if length not in SUPPORTED_LENGTHS or len(w) != length:
        return False
    return w in _normalized_index(length)


def canonical_word(word: str, length: int | None = None) -> str | None:
    """Каноническое написание словарного слова (с ё, если оно у него есть) для
    введённого варианта (с е или ё) — None, если такого слова в словаре нет."""
    w = normalize_yo(word.lower())
    length = len(w) if length is None else length
    if length not in SUPPORTED_LENGTHS or len(w) != length:
        return None
    return _normalized_index(length).get(w)


def _seeded_rng(label: str) -> random.Random:
    """
    Детерминированный, но не предсказуемый снаружи генератор: в сид входит
    серверный секрет (SECRET_KEY), которого нет в публичном репозитории.
    Иначе слово дня можно было бы посчитать заранее по открытым данным —
    tournament_id и номер дня видны игроку, а алгоритм и список слов лежат в
    публичном коде. label — например "day:3:7", разные типы слов не
    пересекаются по сиду.
    """
    secret = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    digest = hashlib.sha256(f"{secret}|{label}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest, "big"))


def pick_word_for_day(
    tournament_id: int, day_number: int, already_used: set[str], length: int = DEFAULT_LENGTH
) -> str:
    """
    Детерминированный выбор слова дня: одинаковый tournament_id + day_number всегда
    дают одно и то же слово (не нужно хранить выбор заранее и он воспроизводим),
    но при этом слово не повторяется в рамках розыгрыша (already_used — уже
    использованные слова в этом розыгрыше, передаются из БД).
    """
    words = load_words(length)
    rng = _seeded_rng(f"day:{tournament_id}:{day_number}")
    candidates = [w for w in words if w not in already_used]
    if not candidates:
        raise RuntimeError("Словарь исчерпан — слов для нового дня не осталось")
    return rng.choice(candidates)


def pick_word_for_label(label: str, already_used: set[str], length: int = DEFAULT_LENGTH) -> str:
    """
    Детерминированный выбор слова по произвольной метке сида (например,
    "marathon:<розыгрыш>:<участник>:<номер>" для личных наборов слов марафона) —
    так же, как pick_word_for_day: слово не повторяет already_used.
    """
    words = load_words(length)
    rng = _seeded_rng(label)
    candidates = [w for w in words if w not in already_used]
    if not candidates:
        raise RuntimeError("Словарь исчерпан — слов для нового набора не осталось")
    return rng.choice(candidates)


def pick_word_for_match(
    match_id: int, game_number: int, already_used: set[str], length: int = DEFAULT_LENGTH
) -> str:
    """
    Детерминированный выбор слова для конкретной игры внутри пары сетки —
    аналог pick_word_for_day, но сид строится из id пары и номера игры (у пар
    нет единого "номера дня розыгрыша", как у обычных дней).

    Слово зависит от already_used только если "основной" выбор по сиду в нём
    уже есть: тогда берётся следующий по тому же сиду. Раньше выбор шёл из
    списка, отфильтрованного по already_used, поэтому любое изменение набора
    использованных слов (замена слова соседней игры пары, слово из другой
    пары) сдвигало и все остальные превью очереди.
    """
    words = load_words(length)
    rng = _seeded_rng(f"match:{match_id}:{game_number}")
    for _ in range(200):
        word = words[rng.randrange(len(words))]
        if word not in already_used:
            return word
    candidates = [w for w in words if w not in already_used]
    if not candidates:
        raise RuntimeError("Словарь исчерпан — слов для новой игры сетки не осталось")
    return rng.choice(candidates)


def pick_alternative_word(already_used: set[str], exclude: str | None = None, length: int = DEFAULT_LENGTH) -> str:
    """
    Выбор нового случайного предложения взамен текущего (кнопка "предложить
    другое слово" в админке) — в отличие от pick_word_for_day, недетерминирован:
    иначе повторное нажатие всегда возвращало бы то же самое слово.
    exclude — текущее предложенное слово, чтобы не предложить его же снова.
    """
    words = load_words(length)
    excluded = already_used | ({exclude} if exclude else set())
    candidates = [w for w in words if w not in excluded]
    if not candidates:
        raise RuntimeError("Словарь исчерпан — новых слов для замены не осталось")
    return random.choice(candidates)


def validate_manual_word(word: str, already_used: set[str], length: int | None = None) -> str | None:
    """
    Проверка слова, которое администратор вводит вручную взамен предложенного.
    Возвращает текст ошибки (для показа в UI) или None, если всё в порядке.
    length=None — допустима любая поддерживаемая длина (ручное слово главнее
    плана длин); иначе слово должно быть ровно такой длины.
    """
    word = word.lower().strip()
    if length is None:
        if len(word) not in SUPPORTED_LENGTHS:
            return "Слово должно быть из 5, 6 или 7 букв"
        length = len(word)
    elif len(word) != length:
        return f"Слово должно быть из {length} букв"
    if not is_valid_word(word, length):
        return "Слово должно быть существительным в именительном падеже из словаря"
    already_used_normalized = {normalize_yo(w) for w in already_used}
    if normalize_yo(word) in already_used_normalized:
        return "Это слово уже использовалось в этом розыгрыше"
    return None
