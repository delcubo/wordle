from datetime import date
from pydantic import BaseModel


class AdminLoginRequest(BaseModel):
    password: str


# ---------- Общие настройки сайта ----------

class ThemeOut(BaseModel):
    theme: str  # "dark" | "light"


class ThemeUpdateRequest(BaseModel):
    theme: str  # "dark" | "light"


# ---------- Users ----------

class UserCreateRequest(BaseModel):
    admin_note: str | None = None
    is_test: bool = False


class UserTournamentInfo(BaseModel):
    tournament_id: int
    title: str
    active: bool


class UserOut(BaseModel):
    id: int
    access_token: str
    admin_note: str | None
    created_at: str | None = None
    archived: bool = False
    is_test: bool = False
    tournaments: list[UserTournamentInfo] = []

    class Config:
        from_attributes = True


class UserEditRequest(BaseModel):
    admin_note: str | None = None


class UserArchiveRequest(BaseModel):
    archived: bool


# ---------- Tournaments ----------

class TournamentConfigRequest(BaseModel):
    title: str
    type: str  # "standard" | "knockout" | "championship" | "endless"
    start_date: date
    duration_days: int | None = None  # обязателен для standard/championship, не используется для knockout/endless
    scoring_rules: dict[str, int]  # игнорируется для endless — там нет очков
    skip_flag_symbol: str = "🚩"
    bracket_size: int | None = None       # championship: сколько мест проходит в плей-офф; knockout: общий размер сетки
    rounds_per_match: int = 1


class TournamentOut(BaseModel):
    id: int
    title: str
    type: str
    start_date: date
    duration_days: int | None
    status: str
    scoring_rules: dict[str, int] | None
    skip_flag_symbol: str
    bracket_size: int | None
    rounds_per_match: int

    class Config:
        from_attributes = True


class TournamentSettingsUpdateRequest(BaseModel):
    title: str | None = None  # можно использовать плейсхолдеры {day} (standard/championship) и {stage} (knockout)
    duration_days: int | None = None  # только standard/championship; вниз — не меньше текущего дня


# ---------- Tournament entries ----------

class EntryCreateRequest(BaseModel):
    user_id: int
    callsign: str


class EntryOut(BaseModel):
    id: int
    user_id: int
    callsign: str
    joined_on_day: int
    active: bool = True

    class Config:
        from_attributes = True


class EntryEditRequest(BaseModel):
    callsign: str


class EntryActiveRequest(BaseModel):
    active: bool


# ---------- Daily word confirmation ----------

class DailyWordOut(BaseModel):
    id: int
    day_number: int
    word: str
    calendar_date: date
    status: str

    class Config:
        from_attributes = True


class ConfirmWordRequest(BaseModel):
    override_word: str | None = None  # None = согласиться с предложенным


# ---------- Player-facing game ----------

class MyTournamentOut(BaseModel):
    tournament_id: int
    title: str
    type: str
    callsign: str
    status: str


class TodayWordStatus(BaseModel):
    has_word_today: bool
    already_played: bool
    day_number: int | None = None
    attempts_used: int | None = None
    solved: bool | None = None
    previous_guesses: list[str] = []
    previous_results: list[list[str]] = []  # раскраска каждой прошлой попытки, по буквам
    answer_word: str | None = None  # раскрывается только если игра завершена и не разгадана
    max_attempts: int = 6
    callsign: str | None = None
    tournament_title: str | None = None


class BracketTodayStatus(BaseModel):
    has_match: bool
    match_finished: bool = False
    won: bool | None = None
    opponent_callsign: str | None = None
    opponent_attempts_used: int | None = None
    opponent_solved: bool | None = None
    round_number: int | None = None
    game_number: int | None = None
    is_sudden_death: bool = False
    already_played: bool = False
    attempts_used: int | None = None
    solved: bool | None = None
    previous_guesses: list[str] = []
    previous_results: list[list[str]] = []
    answer_word: str | None = None
    max_attempts: int = 6
    waiting_for_opponent: bool = False
    callsign: str | None = None
    tournament_title: str | None = None


class GuessRequest(BaseModel):
    token: str
    tournament_id: int
    guess: str


class LetterState(BaseModel):
    letter: str
    state: str  # "correct" | "present" | "absent"


class GuessResponse(BaseModel):
    result: list[LetterState]
    solved: bool
    attempts_used: int
    attempts_remaining: int
    game_over: bool
    points: int | None = None


# ---------- Standings ----------

class DailyCell(BaseModel):
    played: bool
    points: int | None
    admin_note: str | None = None
    not_played_yet: bool = False
    guesses: list[str] = []


class StandingsRowOut(BaseModel):
    participant_id: int  # id соответствующего TournamentEntry
    callsign: str
    total_points: int
    place: str
    daily: list[DailyCell]


class StandingsResponse(BaseModel):
    rows: list[StandingsRowOut]
    total_days: int
    skip_flag_symbol: str


# ---------- Тай-брейк ----------

class TiebreakParticipantOut(BaseModel):
    entry_id: int
    callsign: str
    solved: bool | None = None
    attempts_used: int | None = None


class TiebreakRoundOut(BaseModel):
    id: int
    round_number: int
    previous_round_id: int | None
    completed: bool
    word: str
    calendar_date: date
    participants: list[TiebreakParticipantOut]
    manual_order: list[int] | None = None
    admin_note: str | None = None


class TiebreakStartResponse(BaseModel):
    started: bool
    rounds_created: int


class TiebreakOverrideRequest(BaseModel):
    order: list[int]  # entry_id всех участников раунда, от лучшего к худшему
    note: str


# ---------- Сетка плей-офф ----------

class PlayoffMatchOut(BaseModel):
    id: int
    round_number: int
    position: int
    entry_a_id: int | None
    entry_a_callsign: str | None
    entry_a_attempts_used: int | None = None
    entry_a_solved: bool | None = None
    entry_b_id: int | None
    entry_b_callsign: str | None
    entry_b_attempts_used: int | None = None
    entry_b_solved: bool | None = None
    game_number: int | None = None
    is_sudden_death: bool = False
    word: str | None = None
    winner_entry_id: int | None
    status: str
    scheduled_date: date | None
    admin_note: str | None = None


class BracketRound1Request(BaseModel):
    pairs: list[tuple[int, int]]  # (entry_a_id, entry_b_id) для каждой пары раунда 1


class MatchOverrideRequest(BaseModel):
    winner_entry_id: int
    note: str


# ---------- Ручная корректировка результата дня ----------

class DayResultOverrideRequest(BaseModel):
    attempts_used: int
    solved: bool
    note: str


class DayResultOverrideResponse(BaseModel):
    entry_id: int
    day_number: int
    attempts_used: int
    solved: bool
    points: int
    admin_note: str
