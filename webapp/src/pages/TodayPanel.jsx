import { useEffect, useRef, useState } from "react";
import { api, useModes, useIsMobile, panelStyle, ghostButtonStyle } from "./adminShared.jsx";
import WordActions from "./WordActions.jsx";

const REFRESH_MS = 60000;
const RESULTS_SHOWN = 12;
const touch = (isMobile) => (isMobile ? { minHeight: 40 } : {});

function formatClock(date) {
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function Chip({ children, color = "#3a3a3c", title }) {
  return (
    <span title={title} style={{ fontSize: 12, padding: "2px 8px", borderRadius: 4, background: color, whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

// Слово на завтра: те же действия над словом, что и на странице розыгрыша (WordActions), но прямо с карточки.
function NextWord({ word, onChange, onOpenWords, isMobile }) {
  const post = (path, body) => api(path, { method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
  const confirmed = word.status === "confirmed";
  return (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: "1px solid #2a2a2c" }}>
      <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>
        Слово на день {word.day_number} ({word.calendar_date.split("-").reverse().slice(0, 2).join(".")})
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        <span style={{ fontSize: 22, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2 }}>{word.word}</span>
        <Chip color={confirmed ? "#538d4e" : "#b59f3b"}>{confirmed ? "подтверждено" : "предложено системой"}</Chip>
      </div>
      <WordActions
        word={word.word}
        onConfirm={confirmed ? undefined : async () => onChange(await post(`/api/admin/words/${word.id}/confirm`, { override_word: null }))}
        onReroll={async () => onChange(await post(`/api/admin/words/${word.id}/reroll`))}
        onReplace={async (text) => onChange(await post(`/api/admin/words/${word.id}/confirm`, { override_word: text }))}
      >
        <button onClick={onOpenWords} style={{ ...ghostButtonStyle, ...touch(isMobile), opacity: 0.7 }}>Все слова →</button>
      </WordActions>
    </div>
  );
}

function ProgressBar({ done, inProgress, total }) {
  const pct = (n) => (total > 0 ? `${(n / total) * 100}%` : "0%");
  return (
    <div style={{ height: 8, borderRadius: 4, background: "#2a2a2c", overflow: "hidden", display: "flex" }}>
      <div style={{ width: pct(done), background: "#538d4e" }} />
      <div style={{ width: pct(inProgress), background: "#b59f3b" }} />
    </div>
  );
}

function Card({ card, onOpen, onWordChange, isMobile }) {
  const { label } = useModes();
  const [showAll, setShowAll] = useState(false);
  const results = showAll ? card.results : card.results.slice(0, RESULTS_SHOWN);
  const started = card.status !== "draft";
  const needsConfirm = card.next_word && card.next_word.status !== "confirmed";
  return (
    <div style={{ ...panelStyle, border: needsConfirm ? "1px solid #b59f3b" : "1px solid transparent" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 16, overflowWrap: "anywhere" }}>{card.title}</div>
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 2 }}>
            {label(card.type)}{card.label ? ` · ${card.label}` : ""}
          </div>
        </div>
        <button onClick={() => onOpen(card.id, "participants")} style={{ ...ghostButtonStyle, ...touch(isMobile), flexShrink: 0 }}>Открыть →</button>
      </div>

      {card.attention.length > 0 && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {card.attention.map((a) => <Chip key={a} color="#7a5a1c">⚠ {a}</Chip>)}
        </div>
      )}

      {started && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 13, marginBottom: 4 }}>
            Закончили <b>{card.done}</b>{card.players_total ? ` из ${card.players_total}` : ""}
            {card.in_progress > 0 && <span style={{ opacity: 0.7 }}> · играют {card.in_progress}</span>}
          </div>
          <ProgressBar done={card.done} inProgress={card.in_progress} total={card.players_total} />
          {card.results.length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
              {results.map((r) => (
                <Chip key={r.callsign} color={r.done ? "#2f4d2c" : "#4d4326"}>{r.callsign} · {r.text}</Chip>
              ))}
              {card.results.length > RESULTS_SHOWN && (
                <button onClick={() => setShowAll((v) => !v)} style={{ ...ghostButtonStyle, padding: "1px 8px", fontSize: 12 }}>
                  {showAll ? "свернуть" : `ещё ${card.results.length - RESULTS_SHOWN}`}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {card.next_word && (
        <NextWord
          word={card.next_word} isMobile={isMobile}
          onChange={(w) => onWordChange(card.id, w)} onOpenWords={() => onOpen(card.id, "words")}
        />
      )}
    </div>
  );
}

export default function TodayPanel({ onOpen, onNeedConfirmChange }) {
  const isMobile = useIsMobile();
  const [cards, setCards] = useState(null);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);
  const timer = useRef(null);

  async function refresh() {
    try {
      setCards(await api("/api/admin/today"));
      setUpdatedAt(new Date());
      setError("");
    } catch (e) {
      if (e.message !== "unauthorized") setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // обновляем раз в минуту, пока вкладка на экране
    timer.current = setInterval(() => { if (!document.hidden) refresh(); }, REFRESH_MS);
    return () => clearInterval(timer.current);
  }, []);

  const needConfirm = cards ? cards.filter((c) => c.next_word && c.next_word.status !== "confirmed").length : 0;
  useEffect(() => {
    if (onNeedConfirmChange) onNeedConfirmChange(needConfirm);
  }, [needConfirm]);

  function handleWordChange(cardId, word) {
    setCards((prev) => prev.map((c) => (c.id === cardId ? { ...c, next_word: { ...c.next_word, ...word, length: word.word.length } } : c)));
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Сегодня</h2>
          <div style={{ fontSize: 13, opacity: 0.7, marginTop: 2 }}>
            {needConfirm > 0 ? `Слов на завтра к подтверждению: ${needConfirm}` : cards ? "Все слова на завтра подтверждены" : ""}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {updatedAt && <span style={{ fontSize: 12, opacity: 0.6 }}>обновлено {formatClock(updatedAt)}</span>}
          <button onClick={refresh} style={{ ...ghostButtonStyle, ...touch(isMobile) }}>Обновить</button>
        </div>
      </div>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}
      {!cards && !error && <div style={{ opacity: 0.7 }}>Загрузка…</div>}
      {cards && cards.length === 0 && <div style={{ opacity: 0.7 }}>Сейчас нет идущих розыгрышей.</div>}
      {cards && (
        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(auto-fill, minmax(360px, 1fr))", gap: 12, alignItems: "start" }}>
          {cards.map((card) => (
            <Card key={card.id} card={card} onOpen={onOpen} onWordChange={handleWordChange} isMobile={isMobile} />
          ))}
        </div>
      )}
    </div>
  );
}
