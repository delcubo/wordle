const COLORS = {
  correct: "var(--correct)",
  present: "var(--present)",
  absent: "var(--absent)",
  empty: "var(--absent)",
};

const FLIP_DURATION_MS = 450;
const FLIP_STAGGER_MS = 300;
// Сколько всего идёт переворот всей строки из 5 букв — чтобы модалка с итогом
// (см. PlayerGame.jsx) не перекрывала грид раньше, чем доиграет анимация.
export const FLIP_TOTAL_MS = FLIP_DURATION_MS + FLIP_STAGGER_MS * 4;

/**
 * rows: массив по 6 строк, каждая — { letters: string[5], statuses: string[5] | null }
 * currentGuess: то, что игрок вводит прямо сейчас (для незавершённой строки)
 * animateRowIndex: индекс строки, которую только что отправили в этом сеансе —
 * для неё буквы переворачиваются по очереди, раскрывая цвет в середине переворота
 * (как на wordle.belousov.one); строки, уже пришедшие готовыми (при загрузке
 * страницы), просто показываются раскрашенными без анимации.
 */
export default function WordGrid({ rows, currentGuess, activeRowIndex, animateRowIndex }) {
  // Буквы, чья правильная позиция уже известна из предыдущих попыток этой же
  // игры — показываются подсказкой (приглушённым цветом) в ещё не введённых
  // клетках текущей попытки, по аналогии с wordle.belousov.one, чтобы не
  // заставлять игрока держать их в памяти и перепечатывать заново.
  const knownCorrect = Array(5).fill(null);
  rows.forEach((row) => {
    if (!row.statuses) return;
    row.statuses.forEach((s, j) => {
      if (s === "correct") knownCorrect[j] = row.letters[j];
    });
  });

  return (
    <div style={{ display: "grid", gap: "clamp(3px, 1.5vw, 8px)", justifyContent: "center", padding: "10px 0" }}>
      <style>{`
        @keyframes wordgrid-flip {
          0%, 50% { background: transparent; border-color: var(--border-filled); color: var(--fg); }
          0% { transform: rotateX(0deg); }
          50% { transform: rotateX(90deg); }
          50.001%, 100% { background: var(--tile-bg); border-color: var(--tile-bg); color: #fff; }
          100% { transform: rotateX(0deg); }
        }
      `}</style>
      {rows.map((row, i) => {
        const isActive = i === activeRowIndex;
        const statuses = row.statuses;
        const isAnimating = i === animateRowIndex && statuses;

        const ghostFlags = Array(5).fill(false);
        const letters = isActive
          ? Array.from({ length: 5 }, (_, j) => {
              if (j < currentGuess.length) return currentGuess[j];
              if (knownCorrect[j]) {
                ghostFlags[j] = true;
                return knownCorrect[j];
              }
              return "";
            })
          : row.letters ?? Array(5).fill("");

        return (
          <div key={i} style={{ display: "flex", gap: "clamp(4px, 1.5vw, 8px)" }}>
            {letters.map((letter, j) => {
              const isGhost = ghostFlags[j];
              const filled = Boolean(letter.trim()) && !isGhost;
              const graded = statuses && !isAnimating;

              const style = isAnimating
                ? {
                    "--tile-bg": COLORS[statuses[j]],
                    color: "var(--fg)",
                    background: "transparent",
                    border: "2px solid var(--border-filled)",
                    animation: `wordgrid-flip ${FLIP_DURATION_MS}ms ease-in-out ${j * FLIP_STAGGER_MS}ms both`,
                  }
                : {
                    color: graded ? "#fff" : isGhost ? "var(--muted)" : "var(--fg)",
                    background: graded ? COLORS[statuses[j]] : "transparent",
                    border: `2px solid ${graded ? COLORS[statuses[j]] : filled ? "var(--border-filled)" : "var(--border)"}`,
                  };

              return (
                <div
                  key={j}
                  style={{
                    width: "clamp(36px, min(16vw, 7dvh), 64px)",
                    height: "clamp(36px, min(16vw, 7dvh), 64px)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "clamp(16px, min(6vw, 3dvh), 32px)",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    borderRadius: 4,
                    ...style,
                  }}
                >
                  {letter.trim()}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
