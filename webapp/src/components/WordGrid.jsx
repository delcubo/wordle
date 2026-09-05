const COLORS = {
  correct: "#538d4e",
  present: "#b59f3b",
  absent: "#3a3a3c",
  empty: "#3a3a3c",
};

/**
 * rows: массив по 6 строк, каждая — { letters: string[5], statuses: string[5] | null }
 * currentGuess: то, что игрок вводит прямо сейчас (для незавершённой строки)
 */
export default function WordGrid({ rows, currentGuess, activeRowIndex }) {
  return (
    <div style={{ display: "grid", gap: 6, justifyContent: "center", padding: "16px 0" }}>
      {rows.map((row, i) => {
        const isActive = i === activeRowIndex;
        const letters = isActive
          ? (currentGuess + "     ").slice(0, 5).split("")
          : row.letters ?? Array(5).fill("");
        const statuses = row.statuses;

        return (
          <div key={i} style={{ display: "flex", gap: 6 }}>
            {letters.map((letter, j) => (
              <div
                key={j}
                style={{
                  width: 48,
                  height: 48,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 24,
                  fontWeight: 700,
                  color: "#fff",
                  textTransform: "uppercase",
                  background: statuses ? COLORS[statuses[j]] : "transparent",
                  border: `2px solid ${letter.trim() ? "#565758" : "#3a3a3c"}`,
                  borderRadius: 4,
                }}
              >
                {letter.trim()}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
