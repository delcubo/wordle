import { useState } from "react";

const EMOJI = { correct: "🟩", present: "🟨", absent: "⬜" };
const CELL_COLOR = { correct: "var(--correct)", present: "var(--present)", absent: "var(--absent)" };

/**
 * Всплывающее окно результата — и для обычного слова дня, и для матча сетки.
 * props:
 *  - title: отрендеренное название розыгрыша (уже с "день #N" / стадией сетки —
 *    см. api/tournament_title.py)
 *  - callsign: позывной игрока — показывается и попадает в копируемый текст
 *  - hashtag: хэштег розыгрыша, заданный админом; если не задан — просто не
 *    добавляется в копируемый текст (не подставляется дефолт)
 *  - attemptsUsed, solved, grid (list[list["correct"|"present"|"absent"]])
 *  - answerWord: показывается, только если игра завершена и не разгадана
 *  - message: доп. текст под заголовком (ничья/победа/поражение/ожидание соперника)
 *  - onClose
 */
export default function ResultModal({ title, callsign, hashtag, attemptsUsed, solved, grid, answerWord, message, onClose }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const attemptsLabel = solved ? `${attemptsUsed}/6` : "X/6";
    const emojiGrid = grid.map((row) => row.map((s) => EMOJI[s] || "⬜").join("")).join("\n");
    const lines = [`${title} ${attemptsLabel}`];
    if (callsign) lines.push(`Игрок: ${callsign}`);
    lines.push("", emojiGrid);
    if (hashtag) lines.push("", hashtag);
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      setCopied(false);
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg-secondary)", borderRadius: 10, padding: 20, width: 320,
          maxWidth: "90vw", color: "var(--fg)", textAlign: "center",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>{title} {solved ? `${attemptsUsed}/6` : "X/6"}</h3>
          <button
            onClick={onClose}
            style={{ background: "transparent", border: "none", color: "var(--muted)", fontSize: 20, cursor: "pointer", lineHeight: 1 }}
          >
            ×
          </button>
        </div>

        {callsign && <div style={{ marginTop: 4, fontSize: 13, opacity: 0.7 }}>Игрок: {callsign}</div>}
        {message && <div style={{ marginTop: 10, fontSize: 14, opacity: 0.9 }}>{message}</div>}

        {answerWord && (
          <div style={{ marginTop: 10, fontSize: 14, opacity: 0.85 }}>
            Загаданное слово: <b style={{ textTransform: "uppercase" }}>{answerWord}</b>
          </div>
        )}

        <div style={{ display: "grid", gap: 4, justifyItems: "center", margin: "16px 0" }}>
          {grid.map((row, i) => (
            <div key={i} style={{ display: "flex", gap: 4 }}>
              {row.map((s, j) => (
                <div key={j} style={{ width: 26, height: 26, borderRadius: 3, background: CELL_COLOR[s] || "var(--absent)" }} />
              ))}
            </div>
          ))}
        </div>

        {hashtag && <div style={{ marginBottom: 10, fontSize: 13, opacity: 0.6 }}>{hashtag}</div>}

        <button
          onClick={handleCopy}
          style={{
            width: "100%", padding: "10px 0", borderRadius: 6, border: "none",
            background: "var(--correct)", color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer",
          }}
        >
          {copied ? "Скопировано!" : "Скопировать результат"}
        </button>
      </div>
    </div>
  );
}
