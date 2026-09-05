"""
Игра внутри пары сетки плей-офф: подача попыток, определение победителя,
sudden death при ничье и продвижение победителя в следующий раунд.

Отличия от обычного дня: обе стороны хранятся в одной строке PlayoffGame
(entry_a_*/entry_b_*), а не через DailyWord/Attempt — пара всегда ровно из
двух участников, это не нужно.

Победитель пары определяется по ключу (техническое поражение, не угадал,
число попыток) — меньше ключ, лучше результат. Полное совпадение ключей —
ничья, сразу (в тот же день) заводится ещё одна игра (sudden death). Если
участник не сыграл текущую игру до начала следующего дня — ему проставляется
техническое поражение; если не сыграли оба — пара зависает, доигровка вручную
через админку.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentStatus, TournamentEntry, PlayoffMatch, PlayoffMatchStatus, PlayoffGame
from api.tournament_time import today
from api.wordle_logic import check_guess, is_solved
from api import crud

MAX_ATTEMPTS = 6


def _side_for_entry(match: PlayoffMatch, entry_id: int) -> str:
    if entry_id == match.entry_a_id:
        return "a"
    if entry_id == match.entry_b_id:
        return "b"
    raise ValueError("Этот участник не играет в этой паре")


def _result_key(game: PlayoffGame, side: str) -> tuple[bool, bool, int] | None:
    """(техническое_поражение, не_угадал, попыток) — меньше значит лучше.
    None — сторона ещё не закончила текущую игру."""
    technical_loss = getattr(game, f"entry_{side}_technical_loss")
    if technical_loss:
        return (True, True, MAX_ATTEMPTS)
    attempts_used = getattr(game, f"entry_{side}_attempts_used")
    if attempts_used is None:
        return None
    solved = getattr(game, f"entry_{side}_solved")
    return (False, not solved, attempts_used)


async def get_current_game(session: AsyncSession, match: PlayoffMatch) -> PlayoffGame | None:
    games = await crud.list_playoff_games(session, match.id)
    return games[-1] if games else None


async def submit_guess(
    session: AsyncSession, tournament: Tournament, match: PlayoffMatch, entry_id: int, guess: str
) -> tuple[list[str], bool, int, bool]:
    side = _side_for_entry(match, entry_id)
    game = await get_current_game(session, match)
    if game is None:
        raise ValueError("Игра в этой паре ещё не началась")
    if today() < game.calendar_date:
        raise ValueError("Эта игра ещё не началась")

    existing_guesses = getattr(game, f"entry_{side}_guesses")
    if (
        getattr(game, f"entry_{side}_technical_loss")
        or getattr(game, f"entry_{side}_solved")
        or len(existing_guesses) >= MAX_ATTEMPTS
    ):
        raise ValueError("Попытки в этой игре исчерпаны")

    statuses = check_guess(guess, game.word)
    solved = is_solved(statuses)
    attempts_used = len(existing_guesses) + 1
    game_over = solved or attempts_used >= MAX_ATTEMPTS

    await crud.save_playoff_guess(session, game, side, guess, solved, game_over)

    if game_over:
        await resolve_match_if_ready(session, tournament, match)

    return statuses, solved, attempts_used, game_over


async def resolve_match_if_ready(session: AsyncSession, tournament: Tournament, match: PlayoffMatch) -> None:
    if match.status == PlayoffMatchStatus.finished:
        return
    game = await get_current_game(session, match)
    if game is None:
        return

    deadline_passed = game.calendar_date < today()
    key_a = _result_key(game, "a")
    key_b = _result_key(game, "b")

    if key_a is None and key_b is None:
        return
    if (key_a is None or key_b is None) and not deadline_passed:
        return  # ждём вторую сторону

    if key_a is None:
        game.entry_a_technical_loss = True
        key_a = (True, True, MAX_ATTEMPTS)
    if key_b is None:
        game.entry_b_technical_loss = True
        key_b = (True, True, MAX_ATTEMPTS)
    session.add(game)
    await session.commit()

    if key_a[0] and key_b[0]:
        return  # не явились оба — зависает, доигровка вручную через админку

    if key_a == key_b:
        await crud.create_playoff_game(
            session, tournament.id, match.id, game.game_number + 1, today(), is_sudden_death=True
        )
        return

    match.winner_entry_id = match.entry_a_id if key_a < key_b else match.entry_b_id
    match.status = PlayoffMatchStatus.finished
    session.add(match)
    await session.commit()

    await _advance_winner(session, tournament, match)


async def _advance_winner(session: AsyncSession, tournament: Tournament, match: PlayoffMatch) -> None:
    matches_in_round = tournament.bracket_size // (2 ** match.round_number)
    if matches_in_round <= 1:
        tournament.status = TournamentStatus.finished
        session.add(tournament)
        await session.commit()
        return

    sibling_position = match.position + 1 if match.position % 2 == 0 else match.position - 1
    sibling = await crud.get_playoff_match_by_position(session, match.tournament_id, match.round_number, sibling_position)
    if sibling is None or sibling.winner_entry_id is None:
        return  # соперник по сетке ещё не определился

    next_round = match.round_number + 1
    next_position = match.position // 2
    if await crud.get_playoff_match_by_position(session, match.tournament_id, next_round, next_position) is not None:
        return  # уже создан вторым из пары дошедших до этой точки матчей

    if match.position < sibling.position:
        entry_a, entry_b = match.winner_entry_id, sibling.winner_entry_id
    else:
        entry_a, entry_b = sibling.winner_entry_id, match.winner_entry_id

    next_match = await crud.create_playoff_match(session, tournament.id, next_round, next_position, entry_a, entry_b, today())
    await crud.create_playoff_game(session, tournament.id, next_match.id, 1, today())

    match.next_match_id = next_match.id
    sibling.next_match_id = next_match.id
    session.add_all([match, sibling])
    await session.commit()


async def resolve_ready_matches(session: AsyncSession, tournament: Tournament) -> None:
    for match in await crud.list_playoff_matches(session, tournament.id):
        await resolve_match_if_ready(session, tournament, match)


async def get_player_view(session: AsyncSession, tournament: Tournament, entry) -> dict:
    """Статус текущего матча сетки для конкретного участника — для игровой страницы."""
    matches = await crud.list_playoff_matches_for_entry(session, tournament.id, entry.id)
    if not matches:
        return {"has_match": False}

    match = max(matches, key=lambda m: m.round_number)
    if today() < (match.scheduled_date or today()):
        return {"has_match": False}

    side = _side_for_entry(match, entry.id)
    opponent_entry_id = match.entry_b_id if side == "a" else match.entry_a_id
    opponent = await session.get(TournamentEntry, opponent_entry_id) if opponent_entry_id else None

    if match.status == PlayoffMatchStatus.finished:
        return {
            "has_match": True,
            "match_finished": True,
            "won": match.winner_entry_id == entry.id,
            "opponent_callsign": opponent.callsign if opponent else None,
            "round_number": match.round_number,
        }

    game = await get_current_game(session, match)
    if game is None:
        return {"has_match": False}

    opponent_side = "b" if side == "a" else "a"
    return {
        "has_match": True,
        "match_finished": False,
        "opponent_callsign": opponent.callsign if opponent else None,
        "round_number": match.round_number,
        "already_played": getattr(game, f"entry_{side}_attempts_used") is not None,
        "attempts_used": getattr(game, f"entry_{side}_attempts_used"),
        "solved": getattr(game, f"entry_{side}_solved"),
        "previous_guesses": getattr(game, f"entry_{side}_guesses"),
        "waiting_for_opponent": (
            getattr(game, f"entry_{side}_attempts_used") is not None
            and _result_key(game, opponent_side) is None
        ),
    }
