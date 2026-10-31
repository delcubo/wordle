

export const MATCH_STATUS_LABEL = { pending: "ожидает", in_progress: "идёт", finished: "завершён" };

// Опция "игра за 3 место" — только в розыгрышах с сеткой плей-офф от 4 участников.
function formatAttempts(attemptsUsed, solved) {
  if (attemptsUsed == null) return "";
  return `(${solved ? attemptsUsed : "X"}/6)`;
}

// Результат стороны пары по ВСЕМ сыгранным играм: одна игра — как раньше "(3/6)",
// после ничьей — по порядку "(3 · 4 · X/6)", "–" там, где сторона не сыграла.
// Игра, по которой ещё нет ни одного результата (только что созданный доп.
// раунд), не показывается.
export function formatMatchResults(m, side, detailed = false) {
  const other = side === "a" ? "b" : "a";
  const played = (m?.games || []).filter(
    (g) => g[`entry_${side}_attempts_used`] != null || g[`entry_${other}_attempts_used`] != null
  );
  if (played.length === 0) return "";
  if (played.length === 1) {
    const g = played[0];
    return formatAttempts(g[`entry_${side}_attempts_used`], g[`entry_${side}_solved`]);
  }
  const parts = played.map((g) => {
    const used = g[`entry_${side}_attempts_used`];
    if (used == null) return detailed && g[`entry_${side}_technical_loss`] ? "пропуск" : "–";
    return g[`entry_${side}_solved`] ? used : "X";
  });
  // пара из нескольких обязательных игр: итог по ним (неугаданное = 7) и число неугаданных
  const required = m?.games_required || 1;
  const total = m?.[`entry_${side}_total_attempts`];
  const unsolved = m?.[`entry_${side}_unsolved`] || 0;
  const sum = detailed && required > 1 && total != null ? ` Σ${total}${unsolved ? ` (неугад. ${unsolved})` : ""}` : "";
  return `(${parts.join(" · ")}/6)${sum}`;
}
