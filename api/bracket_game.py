"""
Игра внутри пары сетки плей-офф: подача попыток, определение победителя,
sudden death при ничье и продвижение победителя в следующий раунд.

Отличия от обычного дня: обе стороны хранятся в одной строке PlayoffGame
(entry_a_*/entry_b_*), а не через DailyWord/Attempt — пара всегда ровно из
двух участников, это не нужно.

В паре может быть несколько ОБЯЗАТЕЛЬНЫХ игр (PlayoffMatch.games_required, задаётся планом стадии,
word_plan["playoff_games"]): они создаются сразу и играются подряд в день раунда. Победитель — по
сумме попыток обязательных игр (неугаданное слово = FAILED_ATTEMPTS), при равной сумме — у кого
меньше неугаданных слов. Пропуск (не сыграл или не доиграл до конца дня) хотя бы одной обязательной
игры — поражение в паре; пропустили оба — никто не проходит. Полное равенство — ничья, сразу заводится
дополнительная игра (sudden death), которую решает один её результат — по ключу (техническое
поражение, не угадал, число попыток). Для пары с одной обязательной игрой всё работает как раньше. Если
участник не сыграл текущую игру до начала следующего дня — ему проставляется
техническое поражение; если не сыграли оба — пара считается решённой без
победителя (дальше по сетке из неё никто не проходит, ровно как из пустой
пары — см. resolve_bye_if_needed), без ручной доигровки через админку.
"""
import math
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from api.models import (
    Tournament, TournamentType, TournamentStatus, TournamentEntry, PlayoffMatch, PlayoffMatchStatus, PlayoffGame,
)
from api.tournament_time import today
from api.wordle_logic import check_guess, is_solved
from api.dictionary import pick_word_for_match, pick_alternative_word
from api import crud
from api.word_plan import playoff_length, playoff_games_required
from api.attempt_scores import FAILED_ATTEMPTS

MAX_ATTEMPTS = 6
# Сколько первых игр пары админ может задать заранее (текущая + превью на случай
# ничьей). С игры WORD_QUEUE_SIZE + 1 слова снова генерируются автоматически.
WORD_QUEUE_SIZE = 5


def final_round_number(tournament: Tournament) -> int | None:
    """Номер раунда финала (у сетки на N участников их log2(N))."""
    n = tournament.bracket_size
    if not n or n < 2:
        return None
    return int(math.log2(n))


def _loser_entry_id(match: PlayoffMatch) -> int | None:
    """Проигравший сыгранной пары. None, если пара решилась без игры или без
    победителя (пустая/неполная, двойная неявка) — проигравшего в ней нет."""
    if match.winner_entry_id is None or match.entry_a_id is None or match.entry_b_id is None:
        return None
    return match.entry_b_id if match.winner_entry_id == match.entry_a_id else match.entry_a_id


async def _finish_tournament_if_done(session: AsyncSession, tournament: Tournament) -> None:
    """Розыгрыш завершён, когда решён финал и — если он включён и создан —
    игра за 3 место."""
    final_round = final_round_number(tournament)
    matches = await crud.list_playoff_matches(session, tournament.id)
    final = next((m for m in matches if m.round_number == final_round and not m.is_third_place and m.position == 0), None)
    if final is None or final.status != PlayoffMatchStatus.finished:
        return
    third = next((m for m in matches if m.is_third_place), None)
    if third is not None and third.status != PlayoffMatchStatus.finished:
        return
    tournament.status = TournamentStatus.finished
    session.add(tournament)
    await session.commit()


async def ensure_third_place_match(session: AsyncSession, tournament: Tournament) -> PlayoffMatch | None:
    """
    Создаёт игру за 3 место, если опция включена, оба полуфинала решены и у
    каждого есть проигравший. Играется в день финала (в тот же день, что и
    финал; если финал уже идёт — сегодня). Повторный вызов ничего не делает.
    """
    if not tournament.third_place_match or not tournament.bracket_size or tournament.bracket_size < 4:
        return None
    final_round = final_round_number(tournament)
    matches = await crud.list_playoff_matches(session, tournament.id)
    if any(m.is_third_place for m in matches):
        return None
    semis = sorted(
        (m for m in matches if m.round_number == final_round - 1 and not m.is_third_place), key=lambda m: m.position
    )
    if len(semis) != 2 or any(m.status != PlayoffMatchStatus.finished for m in semis):
        return None
    losers = [_loser_entry_id(m) for m in semis]
    if any(entry_id is None for entry_id in losers):
        return None  # в одном из полуфиналов нет проигравшего — пары для матча нет

    final = next((m for m in matches if m.round_number == final_round and not m.is_third_place and m.position == 0), None)
    if final is not None and final.status == PlayoffMatchStatus.finished:
        return None
    if final is not None and final.scheduled_date is not None:
        match_date = final.scheduled_date
    else:
        round_date = semis[0].scheduled_date or semis[1].scheduled_date or today()
        match_date = round_date + timedelta(days=1)
    match_date = max(match_date, today())

    match = await crud.create_playoff_match(
        session, tournament.id, final_round, 1, losers[0], losers[1], match_date, is_third_place=True
    )
    await resolve_bye_if_needed(session, match, match_date)  # обе стороны есть — заводит игру 1
    return match


async def set_third_place_match(session: AsyncSession, tournament: Tournament, enabled: bool) -> None:
    """Включение/отключение опции "игра за 3 место" (см. ensure_third_place_match).
    Отключить можно, пока в уже созданном матче нет ни одной догадки — тогда он
    удаляется; после первой догадки результаты остаются и отключать нельзя."""
    if tournament.type not in (TournamentType.championship, TournamentType.knockout):
        raise ValueError("Игра за 3 место доступна только в розыгрышах с сеткой плей-офф")
    if not tournament.bracket_size or tournament.bracket_size < 4:
        raise ValueError("Для игры за 3 место нужна сетка минимум на 4 участника")

    if enabled:
        if tournament.status == TournamentStatus.finished:
            raise ValueError("Розыгрыш уже завершён — включить игру за 3 место поздно")
        tournament.third_place_match = True
        session.add(tournament)
        await session.commit()
        await ensure_third_place_match(session, tournament)
        return

    third = next((m for m in await crud.list_playoff_matches(session, tournament.id) if m.is_third_place), None)
    if third is not None:
        games = await crud.list_playoff_games(session, third.id)
        if any(g.entry_a_guesses or g.entry_b_guesses for g in games):
            raise ValueError("Игра за 3 место уже началась — отключить её нельзя")
        for game in games:
            await session.delete(game)
        await session.delete(third)
    tournament.third_place_match = False
    session.add(tournament)
    await session.commit()
    await _finish_tournament_if_done(session, tournament)  # финал мог ждать только этот матч


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


def game_done(game: PlayoffGame, side: str) -> bool:
    """Сторона закончила эту игру (угадала/исчерпала попытки) либо ей засчитано техническое поражение."""
    return bool(getattr(game, f"entry_{side}_technical_loss")) or getattr(game, f"entry_{side}_attempts_used") is not None


def current_game_for_side(games: list[PlayoffGame], side: str) -> PlayoffGame | None:
    """Игра, которую эта сторона играет сейчас: первая по порядку, которую она ещё не закончила
    (обязательные игры идут подряд, дополнительная появляется только после ничьей)."""
    return next((g for g in games if not game_done(g, side)), None)


async def current_game_for_entry(session: AsyncSession, match: PlayoffMatch, entry_id: int) -> PlayoffGame | None:
    return current_game_for_side(await crud.list_playoff_games(session, match.id), _side_for_entry(match, entry_id))


def mandatory_games(match: PlayoffMatch, games: list[PlayoffGame]) -> list[PlayoffGame]:
    return [g for g in games if g.game_number <= (match.games_required or 1)]


def side_score(games: list[PlayoffGame], side: str) -> tuple[int, int]:
    """(сумма попыток, число неугаданных слов) по сыгранным играм стороны; неугаданное — FAILED_ATTEMPTS."""
    total = unsolved = 0
    for g in games:
        if getattr(g, f"entry_{side}_technical_loss") or getattr(g, f"entry_{side}_attempts_used") is None:
            continue
        if getattr(g, f"entry_{side}_solved"):
            total += getattr(g, f"entry_{side}_attempts_used")
        else:
            total += FAILED_ATTEMPTS
            unsolved += 1
    return total, unsolved


async def submit_guess(
    session: AsyncSession, tournament: Tournament, match: PlayoffMatch, entry_id: int, guess: str
) -> tuple[list[str], bool, int, bool]:
    side = _side_for_entry(match, entry_id)
    games = await crud.list_playoff_games(session, match.id)
    if not games:
        raise ValueError("Игра в этой паре ещё не началась")
    current = current_game_for_side(games, side)
    if current is None:
        raise ValueError("Попытки в этой паре исчерпаны")
    # Строка игры блокируется до коммита в save_playoff_guess — все проверки
    # ниже и запись попытки идут по актуальному состоянию, а параллельные
    # запросы того же игрока выстраиваются в очередь.
    game = await crud.lock_playoff_game(session, current.id)
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


async def _finish_match(
    session: AsyncSession, tournament: Tournament, match: PlayoffMatch, winner_entry_id: int | None
) -> None:
    match.winner_entry_id = winner_entry_id
    match.status = PlayoffMatchStatus.finished
    session.add(match)
    await session.commit()
    await advance_winner(session, tournament, match)


async def resolve_match_if_ready(session: AsyncSession, tournament: Tournament, match: PlayoffMatch) -> None:
    if match.status == PlayoffMatchStatus.finished:
        return
    games = await crud.list_playoff_games(session, match.id)
    if not games:
        return
    required = match.games_required or 1
    if len(games) > required:
        # идёт дополнительная игра (после ничьей) — её один результат решает пару, как раньше
        await _resolve_by_single_game(session, tournament, match, games[-1])
        return

    # обязательные игры: решаем, когда обе стороны закончили их все либо вышел срок дня раунда
    mandatory = mandatory_games(match, games)
    deadline_passed = mandatory[0].calendar_date < today()
    done_a = all(game_done(g, "a") for g in mandatory)
    done_b = all(game_done(g, "b") for g in mandatory)
    if not (done_a and done_b):
        if not deadline_passed:
            return  # ждём, пока доиграют обе стороны
        # срок вышел: не сыгранные (не начатые или не законченные) игры — пропуск, то есть техническое поражение
        for g in mandatory:
            for side in ("a", "b"):
                if not game_done(g, side):
                    setattr(g, f"entry_{side}_technical_loss", True)
            session.add(g)
        await session.commit()

    forfeit_a = any(g.entry_a_technical_loss for g in mandatory)
    forfeit_b = any(g.entry_b_technical_loss for g in mandatory)
    if forfeit_a and forfeit_b:
        # пропустили оба — пара решена без победителя, дальше по сетке не проходит никто
        await _finish_match(session, tournament, match, None)
        return
    if forfeit_a or forfeit_b:
        await _finish_match(session, tournament, match, match.entry_b_id if forfeit_a else match.entry_a_id)
        return

    score_a, score_b = side_score(mandatory, "a"), side_score(mandatory, "b")  # (сумма попыток, неугаданных)
    if score_a == score_b:
        await crud.create_playoff_game(
            session, tournament.id, match.id, games[-1].game_number + 1, today(), is_sudden_death=True
        )
        return
    await _finish_match(session, tournament, match, match.entry_a_id if score_a < score_b else match.entry_b_id)


async def _resolve_by_single_game(
    session: AsyncSession, tournament: Tournament, match: PlayoffMatch, game: PlayoffGame
) -> None:
    deadline_passed = game.calendar_date < today()
    key_a = _result_key(game, "a")
    key_b = _result_key(game, "b")

    if key_a is None and key_b is None:
        if not deadline_passed:
            return  # ждём хотя бы одного участника
        await _finish_match(session, tournament, match, None)
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
        await _finish_match(session, tournament, match, None)  # оба технически проиграли — никто не проходит
        return

    if key_a == key_b:
        await crud.create_playoff_game(
            session, tournament.id, match.id, game.game_number + 1, today(), is_sudden_death=True
        )
        return

    await _finish_match(session, tournament, match, match.entry_a_id if key_a < key_b else match.entry_b_id)


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
        for number in range(1, (match.games_required or 1) + 1):  # все обязательные игры — сразу
            await crud.create_playoff_game(session, match.tournament_id, match.id, number, scheduled_date or today())
        return False

    if match.entry_a_id is None and match.entry_b_id is None:
        match.winner_entry_id = None
        match.status = PlayoffMatchStatus.finished
        session.add(match)
        await session.commit()
        return True

    if require_play:
        missing_side = "a" if match.entry_a_id is None else "b"
        for number in range(1, (match.games_required or 1) + 1):
            game = await crud.create_playoff_game(session, match.tournament_id, match.id, number, scheduled_date or today())
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
    if match.is_third_place:
        # игра за 3 место никого дальше не ведёт — только может завершить розыгрыш
        await _finish_tournament_if_done(session, tournament)
        return

    final_round = final_round_number(tournament)
    if final_round is not None and match.round_number == final_round - 1:
        await ensure_third_place_match(session, tournament)  # создастся, когда решатся оба полуфинала

    matches_in_round = tournament.bracket_size // (2 ** match.round_number)
    if matches_in_round <= 1:
        await _finish_tournament_if_done(session, tournament)
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

    # Каждый раунд играется РОВНО один день, раунды идут подряд без пропусков:
    # следующий раунд стартует на следующий день ПОСЛЕ ДНЯ ЭТОГО РАУНДА (а не
    # "сегодня+1" от момента, когда конкретная пара фактически решилась) —
    # иначе у пар, решённых с опозданием (например, после разрешения зависшей
    # из-за двойной неявки соседней пары — см. resolve_match_if_ready), новый
    # раунд стартовал бы позже, чем у остальных пар того же раунда, и игры
    # одного раунда расползлись бы по разным дням. Если разрешение опоздало
    # настолько, что расчётная дата уже в прошлом, — не заводим раунд задним
    # числом, начинаем его сегодня (клэмп по today()).
    round_date = match.scheduled_date or sibling.scheduled_date or today()
    next_start = max(round_date + timedelta(days=1), today())
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


async def get_player_view(session: AsyncSession, tournament: Tournament, entry, game_number: int | None = None) -> dict:
    """
    Статус текущего матча сетки для конкретного участника — для игровой страницы.
    "Текущий" — самый дальний раунд, который УЖЕ НАСТУПИЛ (scheduled_date не в
    будущем): следующий раунд после победы создаётся сразу (см. advance_winner),
    но начинается только на следующий день, и до этого момента он не должен
    заслонять собой ещё не остывший результат только что завершённого раунда —
    иначе игрок-победитель вместо своего попапа с результатом видел бы "матч
    недоступен" вплоть до начала следующего раунда (см. пункт бэклога).

    В паре с несколькими обязательными играми игрок проходит их подряд: показывается его текущая
    (первая не законченная им) игра; когда все закончены — последняя. Результаты соперника по играм
    видны только когда матч решён. game_number — показать результат именно этой игры (для отчёта
    о только что законченной игре, когда у игрока уже есть следующая).
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

    games = await crud.list_playoff_games(session, match.id)
    if not games:
        return {"has_match": False}
    required = match.games_required or 1
    mine_current = current_game_for_side(games, side)
    game = next((g for g in games if g.game_number == game_number), None) if game_number else None
    game = game or mine_current or games[-1]
    mandatory = mandatory_games(match, games)

    my_guesses = getattr(game, f"entry_{side}_guesses")
    my_attempts_used = getattr(game, f"entry_{side}_attempts_used")
    my_solved = getattr(game, f"entry_{side}_solved")
    my_previous_results = [check_guess(g, game.word) for g in my_guesses]
    my_total, my_unsolved = side_score(mandatory, side)
    common = {
        "has_match": True,
        "opponent_callsign": opponent.callsign if opponent else None,
        "round_number": match.round_number,
        "is_third_place": match.is_third_place,
        "word_length": len(game.word),
        "game_number": game.game_number,
        "is_sudden_death": game.is_sudden_death,
        "games_required": required,
        "my_total_attempts": my_total,
        "my_unsolved": my_unsolved,
        "attempts_used": my_attempts_used,
        "solved": my_solved,
        "previous_guesses": my_guesses,
        "previous_results": my_previous_results,
    }

    if match.status == PlayoffMatchStatus.finished:
        # матч решён — можно показать и мои, и соперника результаты по всем играм, включая слово,
        # если я не угадал
        opp_total, opp_unsolved = side_score(mandatory, opponent_side)
        return {
            **common,
            "match_finished": True,
            "won": match.winner_entry_id == entry.id,
            "opponent_attempts_used": getattr(game, f"entry_{opponent_side}_attempts_used"),
            "opponent_solved": getattr(game, f"entry_{opponent_side}_solved"),
            "opponent_total_attempts": opp_total,
            "opponent_unsolved": opp_unsolved,
            "already_played": True,
            "answer_word": None if my_solved else game.word,
            "games": [
                {
                    "game_number": g.game_number, "is_sudden_death": g.game_number > required,
                    "my_attempts_used": getattr(g, f"entry_{side}_attempts_used"), "my_solved": getattr(g, f"entry_{side}_solved"),
                    "my_technical_loss": bool(getattr(g, f"entry_{side}_technical_loss")),
                    "opponent_attempts_used": getattr(g, f"entry_{opponent_side}_attempts_used"),
                    "opponent_solved": getattr(g, f"entry_{opponent_side}_solved"),
                    "opponent_technical_loss": bool(getattr(g, f"entry_{opponent_side}_technical_loss")),
                }
                for g in games
            ],
        }

    already_played = mine_current is None  # все доступные мне игры закончены
    return {
        **common,
        "match_finished": False,
        "already_played": already_played,
        "waiting_for_opponent": already_played and current_game_for_side(games, opponent_side) is not None,
    }


async def sync_games_required(session: AsyncSession, tournament: Tournament) -> int:
    """Приводит число обязательных игр ещё НЕ начатых пар к плану стадий (word_plan["playoff_games"]):
    недостающие игры создаются, лишние (никем не сыгранные) удаляются. Начатые, решённые и пары с
    уже заведённой дополнительной игрой не трогаются. Возвращает, у скольких пар число игр изменилось."""
    changed = 0
    for match in await crud.list_playoff_matches(session, tournament.id):
        if match.status == PlayoffMatchStatus.finished or match.entry_a_id is None or match.entry_b_id is None:
            continue
        target = playoff_games_required(tournament, match.round_number, match.is_third_place)
        required = match.games_required or 1
        if target == required:
            continue
        games = await crud.list_playoff_games(session, match.id)
        if not games or len(games) > required or games[0].calendar_date < today():
            continue
        if any(
            g.entry_a_guesses or g.entry_b_guesses or g.entry_a_attempts_used is not None
            or g.entry_b_attempts_used is not None or g.entry_a_technical_loss or g.entry_b_technical_loss
            for g in games
        ):
            continue  # пара уже началась
        if target > required:
            for number in range(required + 1, target + 1):
                await crud.create_playoff_game(session, tournament.id, match.id, number, games[0].calendar_date)
        else:
            for g in games:
                if g.game_number > target:
                    await session.delete(g)
        match.games_required = target
        session.add(match)
        await session.commit()
        changed += 1
    return changed


def game_word_editable(game: PlayoffGame, match: PlayoffMatch) -> bool:
    """Слово игры можно менять до её дня, а в сам день — пока ни у одной из
    сторон нет ни одной догадки (слово игроку не показывается до конца партии,
    так что пустая сетка ничего не выдаёт). Прошедший день или решённая пара —
    уже нельзя."""
    if game.calendar_date > today():
        return True
    if game.calendar_date < today() or match.status == PlayoffMatchStatus.finished:
        return False
    return not (game.entry_a_guesses or game.entry_b_guesses)


async def get_word_queue(session: AsyncSession, match: PlayoffMatch) -> list[dict]:
    """
    Очередь из WORD_QUEUE_SIZE слов пары — первое уже действующее (или сразу станет им),
    второе и третье — превью на случай ничьей/повторной ничьей, ещё не
    существующих как PlayoffGame. Игры с 4-й дальше не входят в очередь —
    для них слово всегда генерируется автоматически в момент ничьей (см.
    пункт бэклога). Редактируемо: игры 2..N — пока не созданы; созданная игра
    (в т.ч. игра 1) — до её дня и в сам день, пока никто не сделал ни одной
    догадки (см. game_word_editable).
    """
    games = await crud.list_playoff_games(session, match.id)
    games_by_number = {g.game_number: g for g in games}
    overrides = match.word_overrides or {}
    already_used = await crud.get_all_used_words(session, match.tournament_id)
    tournament = await session.get(Tournament, match.tournament_id)

    queue = []
    for game_number in range(1, WORD_QUEUE_SIZE + 1):
        existing = games_by_number.get(game_number)
        if existing is not None:
            word = existing.word
            editable = game_word_editable(existing, match)
        else:
            override = overrides.get(str(game_number))
            if override:
                word = override
            else:
                length = playoff_length(tournament, match.round_number, game_number, match.is_third_place)
                word = pick_word_for_match(match.id, game_number, already_used, length)
            already_used = already_used | {word}
            editable = True
        queue.append({"game_number": game_number, "word": word, "editable": editable, "length": len(word)})
    return queue


async def sibling_queue_words(session: AsyncSession, match: PlayoffMatch, game_number: int) -> set[str]:
    """Слова остальных слотов очереди этой же пары — чтобы замена одного слота
    не дублировала другой (сами слоты при этом друг от друга не зависят)."""
    return {q["word"] for q in await get_word_queue(session, match) if q["game_number"] != game_number}


async def reroll_word_queue_slot(
    session: AsyncSession, match: PlayoffMatch, game_number: int, length: int | None = None
) -> str:
    """"Предложить другое слово" для слота очереди (см. пункт бэклога — раньше
    в сетке можно было только вручную задать своё слово, без реролла, в
    отличие от обычного слова дня). Если игра уже реально существует (не
    наступила — иначе сюда и не попадём, см. editable в get_word_queue),
    меняет её слово; иначе просто перезаписывает превью-оверрайд.
    length — длина нового слова (смена длины позиции); по умолчанию сохраняется
    длина текущего слова слота (а если слот ещё без слова — длина по плану)."""
    games = await crud.list_playoff_games(session, match.id)
    existing = next((g for g in games if g.game_number == game_number), None)
    already_used = await crud.get_all_used_words(session, match.tournament_id)
    already_used = already_used | await sibling_queue_words(session, match, game_number)
    current = (match.word_overrides or {}).get(str(game_number))

    if length is None:
        if existing is not None:
            length = len(existing.word)
        elif current:
            length = len(current)
        else:
            tournament = await session.get(Tournament, match.tournament_id)
            length = playoff_length(tournament, match.round_number, game_number, match.is_third_place)

    if existing is not None:
        new_word = pick_alternative_word(already_used, exclude=existing.word, length=length)
        await crud.set_playoff_game_word(session, existing, new_word)
    else:
        new_word = pick_alternative_word(already_used, exclude=current, length=length)
        await crud.set_playoff_word_override(session, match, game_number, new_word)
    return new_word
