"""
Собирает данные из БД в форму, которую понимает чистая логика в api/scoring.py,
и строит итоговую таблицу для админ-панели (лидерборд + таблица по дням с флагами).
"""
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Tournament, Attempt
from api import crud
from api.scoring import build_standings, ParticipantDayResult, StandingsRow
from api.tournament_time import today, day_number_for_date


async def compute_standings(session: AsyncSession, tournament: Tournament) -> list[StandingsRow]:
    test_user_ids = await crud.get_test_user_ids(session)
    entries = [e for e in await crud.list_entries(session, tournament.id) if e.user_id not in test_user_ids]
    daily_words = await crud.list_daily_words(session, tournament.id)
    attempts = await crud.list_attempts_for_tournament(session, tournament.id)

    daily_word_by_id = {dw.id: dw for dw in daily_words}
    attempts_by_entry_and_day: dict[int, dict[int, Attempt]] = {}
    for a in attempts:
        dw = daily_word_by_id.get(a.daily_word_id)
        if dw is None:
            continue
        attempts_by_entry_and_day.setdefault(a.entry_id, {})[dw.day_number] = a

    current_day = day_number_for_date(tournament.start_date, today())

    daily_results: dict[int, dict[int, ParticipantDayResult]] = {}
    for day_number in range(1, tournament.duration_days + 1):
        daily_results[day_number] = {}
        # Сегодняшний день ещё не закончился (дедлайн — начало следующего дня),
        # а будущие дни ещё не наступили вовсе — непройденный день считается
        # пропуском (и отмечается флагом) только если он уже полностью прошёл.
        pending = day_number >= current_day
        for p in entries:
            # до регистрации участника прошедший день всё равно считается
            # пропущенным (played=False) — по вашим правилам оба случая
            # (не успел подключиться / просто не сыграл) рисуются одинаково.
            attempt = attempts_by_entry_and_day.get(p.id, {}).get(day_number)
            if attempt is None:
                daily_results[day_number][p.id] = ParticipantDayResult(
                    p.id, p.callsign, played=False, points=None, not_played_yet=pending
                )
            else:
                # день "сыгран", только если попытка завершена (угадано или
                # исчерпаны все 6 попыток) — незавершённая попытка в моменте
                # ещё не должна попадать в таблицу как результат дня.
                finished = attempt.solved or attempt.attempts_used >= 6
                if finished:
                    daily_results[day_number][p.id] = ParticipantDayResult(
                        p.id, p.callsign, played=True, points=attempt.points,
                        admin_note=attempt.admin_note, guesses=attempt.guesses,
                    )
                else:
                    daily_results[day_number][p.id] = ParticipantDayResult(
                        p.id, p.callsign, played=False, points=None,
                        not_played_yet=pending, guesses=attempt.guesses,
                    )

    entry_dicts = [{"id": e.id, "callsign": e.callsign} for e in entries]
    return build_standings(entry_dicts, daily_results, tournament.duration_days)
