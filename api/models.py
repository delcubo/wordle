"""
Схема БД под платформу из нескольких одновременных розыгрышей разных типов.

Ключевое разделение: User — глобальная личность человека (одна постоянная ссылка
на все розыгрыши), TournamentEntry — его участие в конкретном Tournament (свой
позывной на каждый розыгрыш). Attempt и PlayoffMatch ссылаются на entry, а не
на пользователя напрямую — так один и тот же человек в разных розыгрышах играет
под разными позывными и с независимым прогрессом.
"""
import enum
from datetime import datetime, date

from sqlalchemy import (
    Integer, String, Boolean, Date, DateTime, ForeignKey, UniqueConstraint,
    Enum as SAEnum, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class TournamentType(str, enum.Enum):
    standard = "standard"          # простое распределение мест по очкам за N дней
    knockout = "knockout"          # игра на вылет для 2^n игроков, сетка задаётся вручную
    championship = "championship"  # standard N дней + тай-брейк + плей-офф топ-2^n
    endless = "endless"            # бессрочная игра без очков и таблицы — только слово дня


class TournamentStatus(str, enum.Enum):
    draft = "draft"           # создан, ещё не стартовал
    active = "active"         # идёт основной этап
    tiebreak = "tiebreak"     # идёт тай-брейк перед посевом (championship)
    playoff = "playoff"       # идёт плей-офф / сетка на вылет
    finished = "finished"     # завершён


class DailyWordStatus(str, enum.Enum):
    suggested = "suggested"   # предложено системой, админ ещё не подтвердил/не заменил
    confirmed = "confirmed"   # админ явно подтвердил или заменил слово


class PlayoffMatchStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    finished = "finished"


class User(Base):
    """
    Глобальная личность человека — одна постоянная персональная ссылка на все
    розыгрыши, куда его подключит администратор. Регистрирует администратор
    вручную (никакой самостоятельной регистрации нет).
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    access_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    admin_note: Mapped[str | None] = mapped_column(String(200), nullable=True)  # для админа: кто это
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # "Удалить игрока совсем" — на деле перемещение в папку "Удалённые" во
    # вкладке "Игроки" (см. пункт #12 бэклога), без потери исторических данных.
    # Прячет игрока из основного списка админки, но ни на что игровое не влияет.
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    entries: Mapped[list["TournamentEntry"]] = relationship(back_populates="user")


class Tournament(Base):
    """Один розыгрыш. Несколько розыгрышей могут идти параллельно и независимо."""
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    type: Mapped[TournamentType] = mapped_column(SAEnum(TournamentType))
    # Хэштег для копируемого результата (см. ResultModal) — задаётся админом,
    # необязателен: если не задан, строка с хэштегом просто не добавляется.
    hashtag: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Для standard/championship — день 1 основного этапа.
    # Для knockout — дата первого раунда сетки (duration_days не используется).
    # Для endless — день 1 бессрочной игры (duration_days тоже не используется — конца нет).
    start_date: Mapped[date] = mapped_column(Date)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # None для endless — там нет очков и таблицы, только слово дня.
    scoring_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"1": 10, "2": 5, ...}
    skip_flag_symbol: Mapped[str] = mapped_column(String(8), default="🚩")

    # Общее число участников сетки (2^n). Для championship — сколько лучших мест
    # основного этапа проходит в плей-офф; для knockout — общий размер турнира.
    bracket_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # сколько основных раундов решает исход пары в сетке (по умолчанию 1)
    rounds_per_match: Mapped[int] = mapped_column(Integer, default=1)

    status: Mapped[TournamentStatus] = mapped_column(
        SAEnum(TournamentStatus), default=TournamentStatus.draft
    )
    # Независимый от status флаг "розыгрыш временно приостановлен админом" —
    # блокирует игру для всех участников без изменения фазы (active/tiebreak/
    # playoff), чтобы можно было включить обратно и продолжить с того же места.
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    # Ручной архив (см. пункт бэклога) — независим от status: раньше в архив
    # автоматически попадали только status=finished, теперь админ сам решает,
    # когда убрать приостановленный или завершённый розыгрыш с глаз долой.
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Заметка админа с описанием розыгрыша — не показывается игрокам.
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entries: Mapped[list["TournamentEntry"]] = relationship(back_populates="tournament")
    daily_words: Mapped[list["DailyWord"]] = relationship(back_populates="tournament")


class TournamentEntry(Base):
    """
    Участие конкретного User в конкретном Tournament — со своим позывным.
    Один и тот же User может иметь несколько TournamentEntry (по одной на розыгрыш).
    """
    __tablename__ = "tournament_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    callsign: Mapped[str] = mapped_column(String(100))

    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # день розыгрыша (1-based), с которого подключён — дни ДО этого числа всё равно
    # помечаются флагом пропуска (см. ранее согласованные правила).
    joined_on_day: Mapped[int] = mapped_column(Integer)

    # Мягкое отключение игрока от розыгрыша админом (не удаляет запись и её
    # Attempt'ы — статистика остаётся в таблице): False = не может больше играть
    # и не видит розыгрыш в "моих розыгрышах", но продолжает учитываться
    # в лидерборде своими уже набранными результатами.
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Не учитывать это участие в таблице результатов розыгрыша (см. пункт
    # бэклога про замену глобального User.is_test на per-entry опцию) —
    # игрок играет как обычно, подключается по своей обычной ссылке, но
    # исключается из compute_standings именно в ЭТОМ розыгрыше.
    hidden_from_standings: Mapped[bool] = mapped_column(Boolean, default=False)

    tournament: Mapped["Tournament"] = relationship(back_populates="entries")
    user: Mapped["User"] = relationship(back_populates="entries")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="entry")


class DailyWord(Base):
    """
    Слово дня для конкретного розыгрыша. day_number — 1-based день розыгрыша
    (для knockout — номер раунда сетки, если у него тоже используется отдельное
    слово вне пары — см. PlayoffGame.word для пар).

    status: suggested — предложено алгоритмом, ещё может быть заменено админом;
    confirmed — либо явно подтверждено, либо наступил дедлайн (начало дня) и
    предложенное слово стало действующим автоматически. Игра использует слово
    независимо от статуса, как только наступила calendar_date — статус нужен
    только для UI администратора ("это предложение, можно ещё поменять" vs
    "уже зафиксировано").
    """
    __tablename__ = "daily_words"
    __table_args__ = (
        UniqueConstraint("tournament_id", "day_number", name="uq_word_per_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    day_number: Mapped[int] = mapped_column(Integer)
    word: Mapped[str] = mapped_column(String(16))
    calendar_date: Mapped[date] = mapped_column(Date)
    status: Mapped[DailyWordStatus] = mapped_column(SAEnum(DailyWordStatus), default=DailyWordStatus.suggested)

    tournament: Mapped["Tournament"] = relationship(back_populates="daily_words")
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="daily_word")


class Attempt(Base):
    """Одна законченная игра участника (TournamentEntry) за день — итог, не отдельная догадка."""
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("entry_id", "daily_word_id", name="uq_attempt_per_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("tournament_entries.id"))
    daily_word_id: Mapped[int] = mapped_column(ForeignKey("daily_words.id"))

    guesses: Mapped[list] = mapped_column(JSON, default=list)
    attempts_used: Mapped[int] = mapped_column(Integer)
    solved: Mapped[bool] = mapped_column(Boolean)
    points: Mapped[int] = mapped_column(Integer)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # заполнено, только если результат этого дня скорректирован админом вручную
    # (см. api/routers/admin.py::override_attempt) — не пусто = не "естественный" результат
    admin_note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    entry: Mapped["TournamentEntry"] = relationship(back_populates="attempts")
    daily_word: Mapped["DailyWord"] = relationship(back_populates="attempts")


class PlayoffMatch(Base):
    """
    Одна пара основной сетки на выбывание (championship после тай-брейка, и
    knockout). Тай-брейк для посева использует отдельные модели ниже
    (TiebreakRound/TiebreakParticipant) — это не пары "1 на 1", а общий раунд
    на всю группу с равными результатами.

    round_number: 1 = первый раунд сетки (например, топ-16), растёт дальше
    (2 = топ-8, ...). Для knockout первый раунд создаёт вручную администратор
    (нет предварительного рейтинга для автопосева); дальнейшие раунды
    заполняются победителями предыдущего через next_match_id.

    position: 0-based номер пары внутри своего раунда — по нему победители пар
    2k и 2k+1 сводятся в пару k следующего раунда (стандартная сетка).
    """
    __tablename__ = "playoff_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))

    round_number: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)

    entry_a_id: Mapped[int | None] = mapped_column(ForeignKey("tournament_entries.id"), nullable=True)
    entry_b_id: Mapped[int | None] = mapped_column(ForeignKey("tournament_entries.id"), nullable=True)

    winner_entry_id: Mapped[int | None] = mapped_column(ForeignKey("tournament_entries.id"), nullable=True)
    status: Mapped[PlayoffMatchStatus] = mapped_column(
        SAEnum(PlayoffMatchStatus), default=PlayoffMatchStatus.pending
    )

    next_match_id: Mapped[int | None] = mapped_column(ForeignKey("playoff_matches.id"), nullable=True)
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # заполнено, только если победитель назначен админом вручную (зависшая или
    # спорная пара), а не обычной игрой — см. api/bracket_game.py::override_winner
    admin_note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Слова, которые админ вручную задал заранее для игр 2 и 3 этой пары (на
    # случай ничьей/повторной ничьей) — см. пункт бэклога про очередь из 3 слов.
    # Ключ — game_number строкой ("2"/"3"), значение — слово. Игра 1 всегда уже
    # существует к моменту создания пары, её слово редактируется напрямую в
    # PlayoffGame.word, сюда не попадает. С игры 4 слова снова генерируются
    # автоматически (оверрайды на них не предусмотрены).
    word_overrides: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    games: Mapped[list["PlayoffGame"]] = relationship(back_populates="match")


class PlayoffGame(Base):
    """
    Один раунд игры внутри пары (обычный раунд или sudden death при ничьей).
    В отличие от обычного дня, обе стороны хранятся прямо в этой строке (а не
    через DailyWord/Attempt) — пара всегда ровно из двух участников.

    calendar_date — день, когда эта конкретная игра стала действующей (для
    game_number=1 это scheduled_date матча; для sudden death — день, когда
    обнаружилась ничья). Дедлайн ("начало следующего дня — техническое
    поражение за неявку") считается от неё же, отдельно для каждой игры.
    """
    __tablename__ = "playoff_games"
    __table_args__ = (
        UniqueConstraint("match_id", "game_number", name="uq_game_per_match"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("playoff_matches.id"))
    game_number: Mapped[int] = mapped_column(Integer)
    word: Mapped[str] = mapped_column(String(16))
    calendar_date: Mapped[date] = mapped_column(Date)
    is_sudden_death: Mapped[bool] = mapped_column(Boolean, default=False)

    entry_a_guesses: Mapped[list] = mapped_column(JSON, default=list)
    entry_a_attempts_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_a_solved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    entry_a_technical_loss: Mapped[bool] = mapped_column(Boolean, default=False)

    entry_b_guesses: Mapped[list] = mapped_column(JSON, default=list)
    entry_b_attempts_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_b_solved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    entry_b_technical_loss: Mapped[bool] = mapped_column(Boolean, default=False)

    match: Mapped["PlayoffMatch"] = relationship(back_populates="games")


class TiebreakRound(Base):
    """
    Общий раунд тай-брейка для группы участников championship, полностью
    совпавших и по очкам, и по числу пропусков (см. scoring.groups_needing_tiebreak)
    — один DailyWord, доступный только участникам этой группы (см.
    TiebreakParticipant); место внутри группы определяется числом попыток на
    это слово (обычные Attempt, как и для любого другого дня).

    Если после раунда часть группы всё ещё равна, для этой подгруппы создаётся
    новый TiebreakRound с previous_round_id, указывающим на текущий, и
    round_number + 1 — рекурсия продолжается, пока порядок не определится
    полностью.
    """
    __tablename__ = "tiebreak_rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"))
    daily_word_id: Mapped[int] = mapped_column(ForeignKey("daily_words.id"))

    round_number: Mapped[int] = mapped_column(Integer, default=1)
    previous_round_id: Mapped[int | None] = mapped_column(ForeignKey("tiebreak_rounds.id"), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)

    # заполнено, только если порядок группы назначен админом вручную (зависший
    # раунд — например, никто из группы не сыграл) — см. api/tiebreak.py::override_round_order.
    # Когда задано, _resolve_group_order отдаёт его как есть, минуя пересчёт по попыткам.
    manual_order: Mapped[list | None] = mapped_column(JSON, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    daily_word: Mapped["DailyWord"] = relationship()
    participants: Mapped[list["TiebreakParticipant"]] = relationship(back_populates="round")


class TiebreakParticipant(Base):
    """Один участник конкретного раунда тай-брейка — кто из группы решает это слово."""
    __tablename__ = "tiebreak_participants"
    __table_args__ = (
        UniqueConstraint("round_id", "entry_id", name="uq_tiebreak_participant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("tiebreak_rounds.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("tournament_entries.id"))

    round: Mapped["TiebreakRound"] = relationship(back_populates="participants")


class AppSettings(Base):
    """
    Единственная строка (id=1) с общими настройками сайта, не привязанными
    к конкретному розыгрышу — сейчас только тема оформления для игроков
    (см. пункт #9 бэклога: переключатель у админа, применяется ко всем сразу).
    """
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme: Mapped[str] = mapped_column(String(10), default="dark")  # "dark" | "light"


class ExcludedWord(Base):
    """
    Слово, которое админ вручную исключил из словаря (нашёл странным/архаичным/
    неуместным по факту игры — см. обсуждение источника словаря). Влияет только
    на выбор БУДУЩИХ слов дня (pick_word_for_day/pick_alternative_word/
    pick_word_for_match) — уже назначенные слова текущих/прошлых дней не
    трогает, и проверку вводимых попыток (is_valid_word) тоже не трогает, чтобы
    случайно не заблокировать игрокам ввод уже загаданного на сегодня слова.
    """
    __tablename__ = "excluded_words"

    id: Mapped[int] = mapped_column(primary_key=True)
    word: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    excluded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AddedWord(Base):
    """
    Слово, которого не было в основном словаре (api/data/answer_words.txt +
    answer_words_extra.txt) и которое админ добавил вручную через панель —
    обнаружилось по факту игры как отсутствующее (см. пункт бэклога).
    В отличие от ExcludedWord хранится в БД, а не в файле репозитория, чтобы
    добавлять слова без деплоя; при старте процесса подгружается в кэш
    словаря (см. api/dictionary.py::register_added_word и api/main.py).
    """
    __tablename__ = "added_words"

    id: Mapped[int] = mapped_column(primary_key=True)
    word: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
