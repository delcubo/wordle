"""
Реестр режимов розыгрыша: какие «модули» (настройки и панели админки) есть у каждого режима.
Единый источник правды для бэкенда (создание розыгрыша, проверки применимости) и для админки: она
получает реестр через GET /api/admin/modes и строит по нему мастер создания, форму настроек, подвкладки
и панели — вместо проверок `type === "..."` по всему коду. Новая возможность режима подключается строкой
в MODULES и записью в modules нужных режимов.
"""
from api.models import TournamentType as T

# модуль -> что он включает (для документации и тестов)
MODULES = {
    # настройки
    "duration": "длительность в днях (основной этап по дням)",
    "scoring": "шкала очков за место",
    "bonus": "бонусные слова",
    "bracket_size": "размер сетки плей-офф",
    "third_place": "игра за 3 место",
    "words_count": "число слов (марафон)",
    "end_date": "дата окончания",
    "individual_words": "личные наборы слов",
    "teams": "командный зачёт",
    "first_place": "первое разыгрываемое место (показ мест тай-брейка)",
    # панели и поведение
    "daily_words": "слово дня: сегодня / на завтра / история",
    "marathon_words": "слова марафона",
    "tiebreak_words": "слова тай-брейка по раундам",
    "standings": "таблица по дням",
    "marathon_results": "таблица марафона",
    "tiebreak_results": "результаты тай-брейка",
    "tiebreak_phase": "тай-брейк перед плей-офф чемпионата",
    "playoff": "сетка плей-офф",
    "tracks_today": "в списке участников видно, кто уже сыграл сегодня",
}

# порядок — как режимы предлагаются в мастере создания
MODES = [
    {
        "type": T.standard,
        "label": "Стандартный",
        "summary": "Несколько дней, одно слово в день; места по сумме очков. Можно включить бонусные слова.",
        "modules": {"duration", "scoring", "bonus", "daily_words", "standings", "tracks_today"},
    },
    {
        "type": T.championship,
        "label": "Чемпионат",
        "summary": "Стандартный этап по дням, затем тай-брейк за места и плей-офф лучших.",
        "modules": {"duration", "scoring", "bonus", "bracket_size", "third_place", "daily_words", "standings",
                    "tiebreak_phase", "playoff"},
    },
    {
        "type": T.knockout,
        "label": "На вылет",
        "summary": "Сетка на вылет: пары играют одно слово или несколько игр, проигравший выбывает.",
        "modules": {"scoring", "bracket_size", "third_place", "playoff", "tracks_today"},
    },
    {
        "type": T.endless,
        "label": "Бессрочная игра",
        "summary": "Слово дня без очков и таблицы, без конца. Одновременно идёт только одна.",
        "modules": {"daily_words", "tracks_today"},
    },
    {
        "type": T.tiebreak,
        "label": "Тай-брейк",
        "summary": "Распределение мест за один день раундами по числу попыток; возможен командный.",
        "modules": {"end_date", "teams", "first_place", "tiebreak_words", "tiebreak_results"},
    },
    {
        "type": T.marathon,
        "label": "Марафон",
        "summary": "Несколько слов подряд; место по числу попыток. Можно личные наборы слов и командный зачёт.",
        "modules": {"words_count", "end_date", "individual_words", "teams", "marathon_words", "marathon_results"},
    },
]

_BY_TYPE = {m["type"]: m for m in MODES}


def has(tournament_type, module: str) -> bool:
    """Есть ли у режима этот модуль (tournament_type — TournamentType или его строковое значение)."""
    mode = _BY_TYPE.get(T(tournament_type))
    return bool(mode) and module in mode["modules"]


def modes_out() -> list[dict]:
    return [
        {"type": m["type"].value, "label": m["label"], "summary": m["summary"], "modules": sorted(m["modules"])}
        for m in MODES
    ]
