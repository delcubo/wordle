"""
Слово дня публикуется в 00:01 по московскому времени — все расчёты "какой сейчас
день розыгрыша" и "какая сегодня календарная дата" идут через таймзону из конфига
(по умолчанию Europe/Moscow), а не через таймзону сервера (Railway обычно UTC).
"""
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_TZ_NAME = os.environ.get("TOURNAMENT_TIMEZONE", "Europe/Moscow")
TOURNAMENT_TZ = ZoneInfo(_TZ_NAME)


def today() -> date:
    """Сегодняшняя календарная дата в таймзоне турнира."""
    return datetime.now(TOURNAMENT_TZ).date()


def day_number_for_date(start_date: date, calendar_date: date) -> int:
    """1-based номер дня розыгрыша для заданной календарной даты."""
    return (calendar_date - start_date).days + 1


def date_for_day_number(start_date: date, day_number: int) -> date:
    return start_date + timedelta(days=day_number - 1)


def next_publish_at() -> datetime:
    """Момент публикации следующего слова (00:01 по таймзоне турнира завтрашней
    календарной даты) — используется для обратного отсчёта в попапе результата
    (см. TodayWordStatus.next_word_at/BracketTodayStatus.next_word_at)."""
    tomorrow = today() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=TOURNAMENT_TZ) + timedelta(minutes=1)
