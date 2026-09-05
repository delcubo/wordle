from datetime import date
from pydantic import BaseModel


class AdminLoginRequest(BaseModel):
    password: str


# ---------- Users ----------

class UserCreateRequest(BaseModel):
    admin_note: str | None = None


class UserOut(BaseModel):
    id: int
    access_token: str
    admin_note: str | None
    created_at: str | None = None

    class Config:
        from_attributes = True


class UserEditRequest(BaseModel):
    admin_note: str | None = None


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


# ---------- Tournament entries ----------

class EntryCreateRequest(BaseModel):
    user_id: int
    callsign: str


class EntryOut(BaseModel):
    id: int
    user_id: int
    callsign: str
    joined_on_day: int

    class Config:
        from_attributes = True


class EntryEditRequest(BaseModel):
    callsign: str


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
    attempts_used: int | None = None
    solved: bool | None = None
    previous_guesses: list[str] = []
    max_attempts: int = 6
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


class TiebreakStartResponse(BaseModel):
    started: bool
    rounds_created: int
