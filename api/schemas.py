from datetime import date
from pydantic import BaseModel


class AdminLoginRequest(BaseModel):
    password: str


# ---------- Общие настройки сайта ----------

class ThemeOut(BaseModel):
    theme: str  # "dark" | "light"


class ThemeUpdateRequest(BaseModel):
    theme: str  # "dark" | "light"


# ---------- Словарь: исключённые слова ----------

class ExcludedWordOut(BaseModel):
    id: int
    word: str
    excluded_at: str | None = None

    class Config:
        from_attributes = True


class ExcludedWordCreateRequest(BaseModel):
    word: str


# ---------- Словарь: добавленные слова ----------

class AddedWordOut(BaseModel):
    id: int
    word: str
    added_at: str | None = None

    class Config:
        from_attributes = True


class AddedWordCreateRequest(BaseModel):
    word: str


# ---------- Users ----------

class UserCreateRequest(BaseModel):
    admin_note: str | None = None


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
    tournaments: list[UserTournamentInfo] = []
    # Позывной из последнего (по дате подключения) участия этого игрока в
    # каком-либо розыгрыше — чтобы подставлять его по умолчанию при подключении
    # к новому (см. пункт бэклога), None — если игрок ещё нигде не участвовал.
    last_callsign: str | None = None

    class Config:
        from_attributes = True


class UserEditRequest(BaseModel):
    admin_note: str | None = None


class UserArchiveRequest(BaseModel):
    archived: bool


# ---------- Tournaments ----------

class TournamentConfigRequest(BaseModel):
    title: str  # чистое название, без плейсхолдеров — день/стадия добавляются автоматически при показе
    type: str  # "standard" | "knockout" | "championship" | "endless"
    start_date: date
    duration_days: int | None = None  # обязателен для standard/championship, не используется для knockout/endless
    scoring_rules: dict[str, int]  # игнорируется для endless — там нет очков
    skip_flag_symbol: str = "🚩"
    bracket_size: int | None = None       # championship: сколько мест проходит в плей-офф; knockout: общий размер сетки
    rounds_per_match: int = 1
    hashtag: str | None = None  # для копируемого результата (ResultModal)
    note: str | None = None  # заметка админа, игрокам не показывается
    words_count: int | None = None  # только marathon: сколько слов подряд
    end_date: date | None = None  # только marathon: последний день игры (необязательно)


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
    hashtag: str | None = None
    paused: bool = False
    archived: bool = False
    notify_admin: bool = False  # присылать админу в Telegram уведомления о завершённых партиях
    first_place: int = 1  # только tiebreak: с какого места разыгрывается диапазон (показ мест)
    note: str | None = None
    third_place_match: bool = False  # опция "игра за 3 место" (сетка плей-офф)
    words_count: int | None = None  # только marathon
    end_date: date | None = None  # только marathon

    class Config:
        from_attributes = True


class TournamentSettingsUpdateRequest(BaseModel):
    title: str | None = None  # чистое название — день/стадия подставляются автоматически при показе
    duration_days: int | None = None  # только standard/championship; вниз — не меньше текущего дня
    hashtag: str | None = None
    note: str | None = None
    start_date: date | None = None  # только пока розыгрыш ещё не стартовал
    notify_admin: bool | None = None
    first_place: int | None = None  # только tiebreak
    third_place_match: bool | None = None  # только championship/knockout, сетка от 4 участников
    words_count: int | None = None  # только marathon: число слов (вверх — можно всегда, вниз — пока слова не начаты)
    end_date: date | None = None  # только marathon
    clear_end_date: bool | None = None  # только marathon: убрать дату окончания


class TournamentPauseRequest(BaseModel):
    paused: bool


class TournamentArchiveRequest(BaseModel):
    archived: bool


# ---------- Tournament entries ----------

class EntryCreateRequest(BaseModel):
    user_id: int
    callsign: str
    hidden_from_standings: bool = False


class EntryOut(BaseModel):
    id: int
    user_id: int
    callsign: str
    joined_on_day: int
    active: bool = True
    hidden_from_standings: bool = False
    # Заполняется для бессрочного, standard и knockout режимов (см. пункт бэклога) — сыграл
    # ли участник уже сегодняшнее слово. Для остальных типов розыгрыша не
    # считается (там видно из таблицы/сетки) и остаётся None.
    played_today: bool | None = None
    # Число попыток на сегодняшнее слово — только когда played_today=True
    # (см. пункт бэклога про формат "n/6" рядом со статусом "Подкл.").
    played_today_attempts: int | None = None
    # Время начала и окончания сегодняшней игры — только когда played_today=True,
    # для отображения времени начала и продолжительности игры (см. пункт бэклога).
    played_today_started_at: str | None = None
    played_today_finished_at: str | None = None
    # Только для knockout: есть ли у участника сегодня игра в паре — чтобы
    # подсвечивать "ещё не играл" только тех, кто сегодня вообще должен играть.
    has_game_today: bool | None = None

    class Config:
        from_attributes = True


class EntryEditRequest(BaseModel):
    callsign: str


class EntryActiveRequest(BaseModel):
    active: bool


class EntryHiddenRequest(BaseModel):
    hidden_from_standings: bool


# ---------- Переброс игроков между розыгрышами ----------

class EntriesTransferRequest(BaseModel):
    entry_ids: list[int]
    to_tournament_id: int


class EntryTransferResult(BaseModel):
    entry_id: int
    callsign: str
    ok: bool
    message: str | None = None  # причина отказа (ok=False) либо примечание при успехе (ok=True)


class EntriesTransferResponse(BaseModel):
    results: list[EntryTransferResult]


# ---------- Daily word confirmation ----------

class DailyWordOut(BaseModel):
    id: int
    day_number: int
    word: str
    calendar_date: date
    status: str
    # заполняется только в /words/today: можно ли ещё заменить слово сегодняшнего дня
    editable: bool = False

    class Config:
        from_attributes = True


class ConfirmWordRequest(BaseModel):
    override_word: str | None = None  # None = согласиться с предложенным


# ---------- Tiebreak (розыгрыш типа tiebreak целиком) ----------

class TiebreakWordQueueEntry(BaseModel):
    day_number: int
    word: str
    editable: bool


class SetTiebreakWordRequest(BaseModel):
    word: str


class TiebreakResultCell(BaseModel):
    solved: bool
    attempts_used: int


class TiebreakResultRound(BaseModel):
    id: int
    round_number: int
    word: str
    completed: bool


class TiebreakResultRow(BaseModel):
    entry_id: int
    callsign: str
    active: bool
    place: str | None
    cells: list[TiebreakResultCell | None]


class TiebreakResultsOut(BaseModel):
    rounds: list[TiebreakResultRound]
    rows: list[TiebreakResultRow]
    first_place: int = 1  # первое разыгрываемое место (места в rows уже сдвинуты)
    last_place: int | None = None  # последнее — по числу участников; None, пока никто не играет


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
    base_title: str | None = None  # название розыгрыша без "#деньN"/стадии — для формата копируемого отчёта в бессрочном режиме
    is_endless: bool = False
    is_standard_report: bool = False  # тот же формат отчёта, что в бессрочном режиме (со звездой вместо ▪️), но для standard/championship на этапе таблицы
    streak_days: int | None = None  # подряд сыгранных дней без пропуска (включая сегодня) — для строки "🔥" в отчёте, см. is_standard_report
    hashtag: str | None = None
    next_word_at: str | None = None  # ISO-момент публикации следующего слова — для попапа-обратного отсчёта
    paused: bool = False
    is_tiebreak: bool = False  # только для розыгрыша типа tiebreak — переключает текст ожидания/финала на фронте
    tiebreak_started: bool = False  # розыгрыш типа tiebreak уже стартовал (хотя бы корневой раунд создан)
    tiebreak_place: str | None = None  # текущее/итоговое место — "2" или диапазон "2-4", пока группа ещё играет
    report_text: str | None = None  # готовый текст отчёта для копирования из попапа (api/report.py) — когда партия закончена
    unavailable_reason: str | None = None  # "not_started" / "finished" — почему слова нет (только когда has_word_today=False), для разных текстов на фронте
    start_date: str | None = None  # ISO-дата старта розыгрыша — для текста "Розыгрыш начнётся 21 сентября" при unavailable_reason="not_started"
    # Марафон (несколько слов подряд): номер текущего слова, всего слов, все пройдены
    is_marathon: bool = False
    word_index: int | None = None
    words_total: int | None = None
    marathon_done: bool = False
    marathon_total_attempts: int | None = None  # сумма попыток по всем словам (неугаданное = 7)


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
    is_third_place: bool = False  # это игра за 3 место
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
    hashtag: str | None = None
    next_word_at: str | None = None
    paused: bool = False
    unavailable_reason: str | None = None  # см. TodayWordStatus
    start_date: str | None = None
    base_title: str | None = None  # название розыгрыша без стадии — для копируемого отчёта
    stage_label: str | None = None  # "1/4 финала" / "финал" и т.п. — метка стадии сетки для копируемого отчёта
    report_text: str | None = None  # готовый текст отчёта для копирования из попапа (api/report.py) — когда игра закончена


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
    # Только марафон, когда слово закончено: ответ (если не угадано), отчёт для
    # копирования, есть ли следующее слово
    answer_word: str | None = None
    report_text: str | None = None
    has_next_word: bool | None = None
    word_index: int | None = None
    words_total: int | None = None
    marathon_total_attempts: int | None = None


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
    tie_resolved: bool = False  # место определено тай-брейком (показывается со звёздочкой)
    daily: list[DailyCell]


class TieGroupMember(BaseModel):
    entry_id: int
    callsign: str


class TieGroupOut(BaseModel):
    place: str  # исходный общий диапазон, например "2-3"
    points: int
    members: list[TieGroupMember]
    suggested_order: list[int] | None = None  # entry_id, лучший первым — по найденному тай-брейку
    suggested_source: str | None = None  # название тай-брейка, откуда взят порядок
    suggestion_note: str | None = None  # почему предложения нет / что с ним не так
    applied_order: list[int] | None = None  # уже применённый порядок
    applied_source: str | None = None


class TieGroupsResponse(BaseModel):
    can_resolve: bool
    reason: str | None = None
    groups: list[TieGroupOut] = []


class TieResolutionItem(BaseModel):
    entry_ids: list[int]  # лучший первым
    source: str = ""


class TieResolutionsRequest(BaseModel):
    resolutions: list[TieResolutionItem]


class StandingsResponse(BaseModel):
    rows: list[StandingsRowOut]
    total_days: int
    current_day: int
    last_completed_day: int = 0  # для списка дней, доступных для выбора в панели (см. admin.py::get_standings)
    skip_flag_symbol: str
    hashtag: str | None = None


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

class PlayoffGameResultOut(BaseModel):
    """Результат одной игры пары (обычной или доп. раунда после ничьей)."""
    game_number: int
    word: str | None = None  # слово игры — только для админки (этот ответ отдаётся админским ручкам)
    is_sudden_death: bool = False
    entry_a_attempts_used: int | None = None
    entry_a_solved: bool | None = None
    entry_b_attempts_used: int | None = None
    entry_b_solved: bool | None = None


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
    is_third_place: bool = False
    # все игры пары по порядку — чтобы в таблице были видны и результаты раундов,
    # закончившихся ничьей, а не только текущей игры
    games: list[PlayoffGameResultOut] = []


class BracketRound1Request(BaseModel):
    # (entry_a_id, entry_b_id) для каждой пары раунда 1 — None у одной или
    # обеих сторон означает неполную/пустую пару (см. пункт бэклога)
    pairs: list[tuple[int | None, int | None]]


class PlayoffWordQueueEntry(BaseModel):
    game_number: int
    word: str
    editable: bool


class SetPlayoffWordRequest(BaseModel):
    word: str


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


# ---------- Марафон (несколько слов подряд) ----------

class MarathonWordOut(BaseModel):
    id: int
    day_number: int  # номер слова по порядку
    word: str
    status: str
    started: int  # сколько участников уже начали это слово
    finished: int  # сколько участников его закончили
    editable: bool  # слово можно заменить: его ещё никто не начал


class MarathonCellOut(BaseModel):
    attempts_used: int
    solved: bool
    finished: bool  # False — слово начато, но ещё не закончено


class MarathonRowOut(BaseModel):
    entry_id: int
    callsign: str
    cells: list[MarathonCellOut | None]  # по слову на ячейку; None — ещё не дошёл
    words_done: int
    total_attempts: int  # сумма попыток по пройденным словам (неугаданное = unsolved_attempts)
    finished_all: bool
    place: str


class MarathonStandingsOut(BaseModel):
    words_count: int
    words: list[dict]
    unsolved_attempts: int
    hashtag: str | None = None
    rows: list[MarathonRowOut]
