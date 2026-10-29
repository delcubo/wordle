"""
Длина слов розыгрыша: базовая (Tournament.word_length: 5, 6 или 7) и точечный
план по позициям (Tournament.word_plan, JSON). Админ сам решает, какой длины
будет слово на конкретной позиции:

  {
    "marathon": [5, 7, 6, 6, 5],                       # слово марафона по номеру
    "playoff":  {"1": [5, 6, 6], "2": [6, 7], "third": [5, 6]},
                                                       # стадия сетки (номер раунда или "third" —
                                                       # игра за 3 место) -> длины игр 1, 2, 3...;
                                                       # дальше повторяется последнее значение
    "tiebreak": [5, 6, 7],                             # раунд тай-брейка по глубине (1, 2, 3...)
    "playoff_games": {"1": 1, "2": 3, "third": 1}      # сколько ОБЯЗАТЕЛЬНЫХ игр в паре стадии (1-5, по умолчанию 1)
  }

Позиция без записи в плане получает базовую длину. План влияет только на ещё не
созданные слова; слово, заданное админом вручную, главнее плана (его длина —
длина самого слова).
"""
from api.dictionary import SUPPORTED_LENGTHS, DEFAULT_LENGTH

PLAYOFF_SLOTS = 5   # сколько первых игр пары админ планирует заранее (см. bracket_game.WORD_QUEUE_SIZE)
THIRD_PLACE_KEY = "third"
MAX_TIEBREAK_DEPTH = 10
MAX_MARATHON_WORDS = 30


def base_length(tournament) -> int:
    return tournament.word_length or DEFAULT_LENGTH


def _plan(tournament) -> dict:
    return tournament.word_plan or {}


def marathon_length(tournament, number: int) -> int:
    """Длина слова марафона с данным номером (1-based)."""
    lengths = _plan(tournament).get("marathon")
    if lengths and 1 <= number <= len(lengths):
        return lengths[number - 1]
    return base_length(tournament)


def playoff_length(tournament, round_number: int, game_number: int, third_place: bool = False) -> int:
    """Длина слова игры пары: стадия (раунд сетки или игра за 3 место) и номер игры в паре."""
    stage = _plan(tournament).get("playoff", {}).get(THIRD_PLACE_KEY if third_place else str(round_number))
    if stage:
        return stage[min(max(game_number, 1), len(stage)) - 1]
    return base_length(tournament)


def playoff_games_required(tournament, round_number: int, third_place: bool = False) -> int:
    """Сколько обязательных игр в паре этой стадии (раунд сетки или игра за 3 место); игры сверх
    этого числа — дополнительные, только при ничьей (см. api/bracket_game.py)."""
    games = _plan(tournament).get("playoff_games", {})
    return int(games.get(THIRD_PLACE_KEY if third_place else str(round_number), 1))


def tiebreak_length(tournament, depth: int) -> int:
    """Длина слова раунда тай-брейка по глубине в цепочке (1 — первый раунд)."""
    lengths = _plan(tournament).get("tiebreak")
    if lengths:
        return lengths[min(max(depth, 1), len(lengths)) - 1]
    return base_length(tournament)


def _clean_lengths(raw, max_items: int, label: str) -> list[int]:
    if not isinstance(raw, list) or not raw or len(raw) > max_items:
        raise ValueError(f"{label}: нужен список из 1–{max_items} длин")
    result = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or value not in SUPPORTED_LENGTHS:
            raise ValueError(f"{label}: длина должна быть одной из {', '.join(map(str, SUPPORTED_LENGTHS))}")
        result.append(value)
    return result


def validate_plan(raw: dict | None) -> dict | None:
    """Проверяет и нормализует присланный план; пустой план — None (всё по базовой длине)."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("План длин должен быть объектом")
    unknown = set(raw) - {"marathon", "playoff", "tiebreak", "playoff_games"}
    if unknown:
        raise ValueError(f"Неизвестные разделы плана: {', '.join(sorted(unknown))}")
    plan: dict = {}
    if raw.get("marathon"):
        plan["marathon"] = _clean_lengths(raw["marathon"], MAX_MARATHON_WORDS, "Марафон")
    if raw.get("tiebreak"):
        plan["tiebreak"] = _clean_lengths(raw["tiebreak"], MAX_TIEBREAK_DEPTH, "Тай-брейк")
    if raw.get("playoff"):
        if not isinstance(raw["playoff"], dict):
            raise ValueError("Плей-офф: нужен объект «стадия -> длины игр»")
        stages = {}
        for key, lengths in raw["playoff"].items():
            if key != THIRD_PLACE_KEY and not (isinstance(key, str) and key.isdigit() and int(key) >= 1):
                raise ValueError("Плей-офф: стадия — номер раунда или «third»")
            if lengths:
                stages[str(key)] = _clean_lengths(lengths, PLAYOFF_SLOTS, f"Плей-офф, стадия {key}")
        if stages:
            plan["playoff"] = stages
    if raw.get("playoff_games"):
        if not isinstance(raw["playoff_games"], dict):
            raise ValueError("Число игр в плей-офф: нужен объект «стадия -> число игр»")
        games = {}
        for key, count in raw["playoff_games"].items():
            if key != THIRD_PLACE_KEY and not (isinstance(key, str) and key.isdigit() and int(key) >= 1):
                raise ValueError("Число игр в плей-офф: стадия — номер раунда или «third»")
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= PLAYOFF_SLOTS:
                raise ValueError(f"Число обязательных игр в паре — от 1 до {PLAYOFF_SLOTS}")
            games[str(key)] = count
        plan["playoff_games"] = games
    return plan or None
