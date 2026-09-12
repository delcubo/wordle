const ROWS = [
  "йцукенгшщзх",
  "фывапролджэ",
  "ячсмитьбю",
];

const COLORS = {
  correct: "var(--correct)",
  present: "var(--present)",
  absent: "var(--absent)",
  default: "var(--key-default)",
};

export default function Keyboard({ letterStates, onLetter, onEnter, onBackspace }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "clamp(4px, 1vw, 8px)",
        width: "100%",
        maxWidth: 560,
        margin: "auto auto 0",
        padding: "0 4px 8px",
        boxSizing: "border-box",
      }}
    >
      {ROWS.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: "clamp(3px, 1vw, 6px)", width: "100%" }}>
          {i === 2 && (
            <KeyButton wide onClick={onEnter} color="var(--key-default-fg)">
              ввод
            </KeyButton>
          )}
          {row.split("").map((letter) => {
            const state = letterStates[letter];
            return (
              <KeyButton
                key={letter}
                onClick={() => onLetter(letter)}
                background={state ? COLORS[state] : COLORS.default}
                color={state ? "#fff" : "var(--key-default-fg)"}
              >
                {letter}
              </KeyButton>
            );
          })}
          {i === 2 && (
            <KeyButton wide onClick={onBackspace} color="var(--key-default-fg)">
              ⌫
            </KeyButton>
          )}
        </div>
      ))}
    </div>
  );
}

function KeyButton({ children, onClick, background = "var(--key-default)", color = "#fff", wide = false }) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: wide ? "1.6 1 0%" : "1 1 0%",
        minWidth: 0,
        height: "clamp(34px, min(12vw, 5.5dvh), 64px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background,
        color,
        border: "none",
        borderRadius: 4,
        fontSize: wide ? "clamp(10px, 3vw, 16px)" : "clamp(13px, 4vw, 20px)",
        fontWeight: 600,
        textTransform: "uppercase",
        cursor: "pointer",
        touchAction: "manipulation",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </button>
  );
}
