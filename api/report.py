"""
Текст отчёта об игре — тот, что игрок копирует из попапа результата. Единый
источник: сервер отдаёт готовый текст (report_text в статусах игры), фронтенд
просто его копирует, а уведомления админу в Telegram (api/notify.py) берут тот
же текст — формат правится в одном месте.

Эмодзи заданы кодовыми точками, а не литералами, чтобы редактор не "съел"
селекторы вариации (у ▪️ и ⚔️ есть U+FE0F) — набор должен совпадать до символа.
"""

GRID_EMOJI = {"correct": "\U0001f7e9", "present": "\U0001f7e8", "absent": "⬜"}  # 🟩 🟨 ⬜
RESULT_EMOJI = {
    1: "\U0001f3af",  # 🎯
    2: "\U0001f9e0",  # 🧠
    3: "\U0001f913",  # 🤓
    4: "\U0001f60e",  # 😎
    5: "\U0001f610",  # 😐
    6: "\U0001f630",  # 😰
}
FAILED_EMOJI = "\U0001f480"  # 💀
BORDER = {
    "endless": "▪️",  # ▪️
    "standard": "★",  # ★
    "bracket": "⚔️",  # ⚔️
    "tiebreak": "\U0001f3b2",  # 🎲
}
STREAK_EMOJI = "\U0001f525"  # 🔥


def build_report_text(
    *,
    kind: str | None,
    attempts_used: int,
    solved: bool,
    grid: list[list[str]],
    callsign: str | None,
    hashtag: str | None,
    base_title: str | None = None,
    day_number: int | None = None,
    stage_label: str | None = None,
    streak_days: int | None = None,
    title: str | None = None,
) -> str:
    """
    kind — формат отчёта: "endless" (▪️, #N), "standard" (★, #дN, строка серии),
    "bracket" (⚔️, метка стадии сетки), "tiebreak" (🎲, "раунд N"); None — прежний
    общий вид (заголовок, "Игрок:", "Попытки:") для остальных случаев, например
    тай-брейка внутри championship. grid — раскраска каждой попытки по буквам
    ("correct"/"present"/"absent").
    """
    emoji_grid = "\n".join("".join(GRID_EMOJI.get(s, GRID_EMOJI["absent"]) for s in row) for row in grid)
    attempts_label = f"{attempts_used}/6" if solved else "X/6"
    has_streak_line = False

    if kind in BORDER and base_title:
        border = BORDER[kind]
        lines = [f"{border} {base_title.upper()} {border}"]
        result_emoji = RESULT_EMOJI.get(attempts_used, FAILED_EMOJI) if solved else FAILED_EMOJI
        if kind == "bracket":
            day_label = stage_label or None
        elif kind == "tiebreak":
            day_label = f"раунд {day_number}" if day_number is not None else None
        elif day_number is not None:
            day_label = f"#{day_number}" if kind == "endless" else f"#д{day_number}"
        else:
            day_label = None
        meta = [part for part in (callsign, day_label, attempts_label) if part]
        lines.append(f"{result_emoji} {' · '.join(meta)}")
        lines += ["", emoji_grid]
        if streak_days is not None and streak_days >= 2:
            lines += ["", f"{STREAK_EMOJI} дней подряд: {streak_days}"]
            has_streak_line = True
    else:
        lines = [title or ""]
        if callsign:
            lines.append(f"Игрок: {callsign}")
        lines.append(f"Попытки: {attempts_label}")
        lines += ["", emoji_grid]

    if hashtag:
        # хештег идёт сразу под строкой серии, без пустой строки между ними
        lines += ([] if has_streak_line else [""]) + [hashtag]
    return "\n".join(lines)
