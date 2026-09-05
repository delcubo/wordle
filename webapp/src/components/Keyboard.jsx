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
    <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center" }}>
      {ROWS.map((row, i) => (
        <div key={i} style={{ display: "flex", gap: 4 }}>
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
        minWidth: wide ? 52 : 28,
        height: 42,
        background,
        color: "#fff",
        border: "none",
        borderRadius: 4,
        fontSize: 13,
        fontWeight: 600,
        textTransform: "uppercase",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
