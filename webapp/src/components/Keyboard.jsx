const ROWS = [
  "йцукенгшщзх",
  "фывапролджэ",
  "ячсмитьбю",
];

const COLORS = {
  correct: "#538d4e",
  present: "#b59f3b",
  absent: "#3a3a3c",
  default: "#818384",
};

export default function Keyboard({ letterStates, onLetter, onEnter, onBackspace }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "clamp(4px, 1vw, 8px)",
        width: "100%",
        maxWidth: 500,
        margin: "0 auto",
        padding: "0 4px",
        boxSizing: "border-box",
      }}
    >
      {ROWS.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: "clamp(3px, 1vw, 6px)", width: "100%" }}>
          {i === 2 && (
            <KeyButton wide onClick={onEnter}>
              ввод
            </KeyButton>
          )}
          {row.split("").map((letter) => (
            <KeyButton
              key={letter}
              onClick={() => onLetter(letter)}
              background={COLORS[letterStates[letter]] ?? COLORS.default}
            >
              {letter}
            </KeyButton>
          ))}
          {i === 2 && (
            <KeyButton wide onClick={onBackspace}>
              ⌫
            </KeyButton>
          )}
        </div>
      ))}
    </div>
  );
}

function KeyButton({ children, onClick, background = "#818384", wide = false }) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: wide ? "1.6 1 0%" : "1 1 0%",
        minWidth: 0,
        height: "clamp(38px, 11vw, 58px)",
        background,
        color: "#fff",
        border: "none",
        borderRadius: 4,
        fontSize: wide ? "clamp(9px, 2.8vw, 13px)" : "clamp(11px, 3.6vw, 16px)",
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
