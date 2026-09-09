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
техническое поражение; если не сыграли оба — пара считается решённой без
победителя (дальше по сетке из неё никто не проходит, ровно как из пустой
пары — см. resolve_bye_if_needed), без ручной доигровки через админку.
"""
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, TournamentStatus, TournamentEntry, PlayoffMatch, PlayoffMatchStatus, PlayoffGame
from api.tournament_time import today
from api.wordle_logic import check_guess, is_solved
from api.dictionary import pick_word_for_match, pick_alternative_word
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
        if not deadline_passed:
            return  # ждём хотя бы одного участника
        # Ни один участник не сыграл вовремя — пара считается решённой без
        # победителя, дальше по сетке из неё никто не проходит (см. пункт
        # бэклога), без ручной доигровки через админку.
        match.winner_entry_id = None
        match.status = PlayoffMatchStatus.finished
        session.add(match)
        await session.commit()
        await advance_winner(session, tournament, match)
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
        # Оба технически проиграли (например, единственный реальный участник
        # неполной пары — см. resolve_bye_if_needed — тоже не явился на свою
        # игру) — как и выше, пара решена без победителя, никто не проходит.
        match.winner_entry_id = None
        match.status = PlayoffMatchStatus.finished
        session.add(match)
        await session.commit()
        await advance_winner(session, tournament, match)
        return

    if key_a == key_b:
        await crud.create_playoff_game(
            session, tournament.id, match.id, game.game_number + 1, today(), is_sudden_death=True
        )
        return

    match.winner_entry_id = match.entry_a_id if key_a < key_b else match.entry_b_id
    match.status = PlayoffMatchStatus.finished
    session.add(match)
    await session.commit()

    await advance_winner(session, tournament, match)


async def resolve_bye_if_needed(
    session: AsyncSession, match: PlayoffMatch, scheduled_date, require_play: bool = False
) -> bool:
    """
    Пара без одного или обоих участников не требует игры от отсутствующей
    стороны — решается сразу:
    - оба слота пусты ("пустая пара", см. пункт бэклога) — у пары просто нет
      победителя, но она сразу считается завершённой, чтобы сосед по сетке не
      ждал её бесконечно;
    - один слот пуст ("неполная пара") — единственный участник обычно
      автоматически побеждает и сразу проходит дальше, без игры (структурный
      бай — соперника для этой позиции не было предусмотрено с самого начала,
      например при нечётном числе участников на первом раунде knockout).

    require_play=True — особый случай: соперник по сетке достался пустым не
    структурно, а из-за того, что соседняя пара не сыграна вовремя (двойная
    неявка, см. resolve_match_if_ready) — тогда свободный проход не даётся:
    единственному участнику всё равно заводится настоящая игра (соперник в
    ней сразу считается технически проигравшим), и пройти дальше можно только
    реально сыграв её; если не сыграет он сам — по тому же правилу пара тоже
    решится без победителя (см. resolve_match_if_ready) и дальше не пройдёт
    никто.

    Возвращает True, если пара была решена БЕЗ игры (полностью пустая, либо
    структурный бай) — тогда вызывающий код должен сам продвинуть её дальше
    через advance_winner. Для require_play с одним участником возвращает
    False — игра создана, ждём её результата как обычно.
    """
    if match.entry_a_id is not None and match.entry_b_id is not None:
        await crud.create_playoff_game(session, match.tournament_id, match.id, 1, scheduled_date or today())
        return False

    if match.entry_a_id is None and match.entry_b_id is None:
        match.winner_entry_id = None
        match.status = PlayoffMatchStatus.finished
        session.add(match)
        await session.commit()
        return True

    if require_play:
        game = await crud.create_playoff_game(session, match.tournament_id, match.id, 1, scheduled_date or today())
        missing_side = "a" if match.entry_a_id is None else "b"
        await crud.set_technical_loss(session, game, missing_side)
        return False

    match.winner_entry_id = match.entry_a_id if match.entry_a_id is not None else match.entry_b_id
    match.status = PlayoffMatchStatus.finished
    session.add(match)
    await session.commit()
    return True


def _forfeited_both_sides(m: PlayoffMatch) -> bool:
    """Пара решена именно двойной неявкой (оба участника были назначены, но
    ни один не сыграл — см. resolve_match_if_ready), а не структурно пустой
    /неполной парой с самого начала (см. resolve_bye_if_needed)."""
    return (
        m.status == PlayoffMatchStatus.finished
        and m.winner_entry_id is None
        and m.entry_a_id is not None
        and m.entry_b_id is not None
    )


async def advance_winner(session: AsyncSession, tournament: Tournament, match: PlayoffMatch) -> None:
    matches_in_round = tournament.bracket_size // (2 ** match.round_number)
    if matches_in_round <= 1:
        tournament.status = TournamentStatus.finished
        session.add(tournament)
        await session.commit()
        return

    sibling_position = match.position + 1 if match.position % 2 == 0 else match.position - 1
    sibling = await crud.get_playoff_match_by_position(session, match.tournament_id, match.round_number, sibling_position)
    # Ждём, пока сосед РЕШИТСЯ (не обязательно с победителем — пустая пара
    # тоже "решена", просто без победителя), а не именно пока появится
    # победитель — иначе пустая пара блокировала бы соседа навсегда.
    if sibling is None or sibling.status != PlayoffMatchStatus.finished:
        return  # соперник по сетке ещё не определился

    next_round = match.round_number + 1
    next_position = match.position // 2
    if await crud.get_playoff_match_by_position(session, match.tournament_id, next_round, next_position) is not None:
        return  # уже создан вторым из пары дошедших до этой точки матчей

    if match.position < sibling.position:
        entry_a, entry_b = match.winner_entry_id, sibling.winner_entry_id
    else:
        entry_a, entry_b = sibling.winner_entry_id, match.winner_entry_id

    # Если пустой слот в новой паре — следствие того, что одна из пар-родителей
    # не сыграна вовремя (двойная неявка), а не структурного бая — свободный
    # проход не даётся, единственному участнику всё равно придётся сыграть
    # свою игру (см. resolve_bye_if_needed).
    require_play = _forfeited_both_sides(match) or _forfeited_both_sides(sibling)

    # Следующий раунд стартует НА СЛЕДУЮЩИЙ день после того, как определилась
    # пара — иначе победители могли бы сыграть его же в день определения пары,
    # пока часть сетки ещё доигрывает текущий раунд.
    next_start = today() + timedelta(days=1)
    next_match = await crud.create_playoff_match(session, tournament.id, next_round, next_position, entry_a, entry_b, next_start)

    match.next_match_id = next_match.id
    sibling.next_match_id = next_match.id
    session.add_all([match, sibling])
    await session.commit()

    # Следующий раунд сам может оказаться пустым/неполным, если сюда каскадом
    # дошёл бай (обе пары этого раунда были пустыми/неполными) — тогда сразу
    # решаем и его и продвигаем дальше.
    if await resolve_bye_if_needed(session, next_match, next_start, require_play=require_play):
        await advance_winner(session, tournament, next_match)


async def resolve_ready_matches(session: AsyncSession, tournament: Tournament) -> None:
    for match in await crud.list_playoff_matches(session, tournament.id):
        await resolve_match_if_ready(session, tournament, match)


async def override_winner(
    session: AsyncSession, tournament: Tournament, match: PlayoffMatch, winner_entry_id: int, note: str
) -> PlayoffMatch:
    """
    Ручное назначение победителя пары (зависшая — оба не явились — или спорная
    пара). Разрешено только пока пара не завершена обычной игрой: победитель
    уже завершённой пары мог пойти дальше и, возможно, уже сыграть следующий
    раунд — откатывать это назад мы не пытаемся.
    """
    if match.status == PlayoffMatchStatus.finished:
        raise ValueError("Эта пара уже завершена — исход можно поменять только напрямую в БД")
    if winner_entry_id not in (match.entry_a_id, match.entry_b_id):
        raise ValueError("Победителем можно назначить только одного из участников этой пары")
    if not note.strip():
        raise ValueError("Нужно указать причину корректировки")

    match.winner_entry_id = winner_entry_id
    match.status = PlayoffMatchStatus.finished
    match.admin_note = note.strip()
    session.add(match)
    await session.commit()

    await advance_winner(session, tournament, match)
    return match


async def get_player_view(session: AsyncSession, tournament: Tournament, entry) -> dict:
    """
    Статус текущего матча сетки для конкретного участника — для игровой страницы.
    "Текущий" — самый дальний раунд, который УЖЕ НАСТУПИЛ (scheduled_date не в
    будущем): следующий раунд после победы создаётся сразу (см. advance_winner),
    но начинается только на следующий день, и до этого момента он не должен
    заслонять собой ещё не остывший результат только что завершённого раунда —
    иначе игрок-победитель вместо своего попапа с результатом видел бы "матч
    недоступен" вплоть до начала следующего раунда (см. пункт бэклога).
    """
    matches = await crud.list_playoff_matches_for_entry(session, tournament.id, entry.id)
    started = [m for m in matches if (m.scheduled_date or today()) <= today()]
    if not started:
        return {"has_match": False}

    match = max(started, key=lambda m: m.round_number)
    side = _side_for_entry(match, entry.id)
    opponent_side = "b" if side == "a" else "a"
    opponent_entry_id = match.entry_b_id if side == "a" else match.entry_a_id
    opponent = await session.get(TournamentEntry, opponent_entry_id) if opponent_entry_id else None

    game = await get_current_game(session, match)
    if game is None:
        return {"has_match": False}

    my_guesses = getattr(game, f"entry_{side}_guesses")
    my_attempts_used = getattr(game, f"entry_{side}_attempts_used")
    my_solved = getattr(game, f"entry_{side}_solved")
    my_previous_results = [check_guess(g, game.word) for g in my_guesses]

    if match.status == PlayoffMatchStatus.finished:
        # матч решён этой (последней сыгранной) игрой — здесь уже можно показать
        # и мой, и соперника результат целиком, включая слово, если я не угадал
        return {
            "has_match": True,
            "match_finished": True,
            "won": match.winner_entry_id == entry.id,
            "opponent_callsign": opponent.callsign if opponent else None,
            "opponent_attempts_used": getattr(game, f"entry_{opponent_side}_attempts_used"),
            "opponent_solved": getattr(game, f"entry_{opponent_side}_solved"),
            "round_number": match.round_number,
            "game_number": game.game_number,
            "is_sudden_death": game.is_sudden_death,
            "already_played": True,
            "attempts_used": my_attempts_used,
            "solved": my_solved,
            "previous_guesses": my_guesses,
            "previous_results": my_previous_results,
            "answer_word": None if my_solved else game.word,
        }

    return {
        "has_match": True,
        "match_finished": False,
        "opponent_callsign": opponent.callsign if opponent else None,
        "round_number": match.round_number,
        "game_number": game.game_number,
        "is_sudden_death": game.is_sudden_death,
        "already_played": my_attempts_used is not None,
        "attempts_used": my_attempts_used,
        "solved": my_solved,
        "previous_guesses": my_guesses,
        "previous_results": my_previous_results,
        "waiting_for_opponent": my_attempts_used is not None and _result_key(game, opponent_side) is None,
    }


async def get_word_queue(session: AsyncSession, match: PlayoffMatch) -> list[dict]:
    """
    Очередь из 3 слов пары — первое уже действующее (или сразу станет им),
    второе и третье — превью на случай ничьей/повторной ничьей, ещё не
    существующих как PlayoffGame. Игры с 4-й дальше не входят в очередь —
    для них слово всегда генерируется автоматически в момент ничьей (см.
    пункт бэклога). Редактируемо: игра 1, пока не наступил её день; игры 2/3 —
    всегда, пока сами ещё не наступили (после наступления они уже реальные
    PlayoffGame и подчиняются тому же правилу "пока не наступил день").
    """
    games = await crud.list_playoff_games(session, match.id)
    games_by_number = {g.game_number: g for g in games}
    overrides = match.word_overrides or {}
    already_used = await crud.get_all_used_words(session, match.tournament_id)

    queue = []
    for game_number in (1, 2, 3):
        existing = games_by_number.get(game_number)
        if existing is not None:
            word = existing.word
            editable = existing.calendar_date > today()
        else:
            override = overrides.get(str(game_number))
            if override:
                word = override
            else:
                word = pick_word_for_match(match.id, game_number, already_used)
            already_used = already_used | {word}
            editable = True
        queue.append({"game_number": game_number, "word": word, "editable": editable})
    return queue


async def reroll_word_queue_slot(session: AsyncSession, match: PlayoffMatch, game_number: int) -> str:
    """"Предложить другое слово" для слота очереди (см. пункт бэклога — раньше
    в сетке можно было только вручную задать своё слово, без реролла, в
    отличие от обычного слова дня). Если игра уже реально существует (не
    наступила — иначе сюда и не попадём, см. editable в get_word_queue),
    меняет её слово; иначе просто перезаписывает превью-оверрайд."""
    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    already_used = await crud.get_all_used_words(session, match.tournament_id)

    if existing is not None:
        new_word = pick_alternative_word(already_used, exclude=existing.word)
        await crud.set_playoff_game_word(session, existing, new_word)
    else:
        current = (match.word_overrides or {}).get(str(game_number))
        new_word = pick_alternative_word(already_used, exclude=current)
        await crud.set_playoff_word_override(session, match, game_number, new_word)
    return new_word
