import { useEffect, useRef, useState } from "react";
import { api, useModes, useIsMobile, panelStyle, ghostButtonStyle } from "./adminShared.jsx";
import WordActions from "./WordActions.jsx";

const REFRESH_MS = 60000;
const RESULTS_SHOWN = 12;
const TONE_COLOR = { good: "#2f4d2c", fail: "#5a2a2a", playing: "#4d4326" };
const SORTS = { rank: "по результату", time: "по времени", name: "по позывному" };
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

// Сводка вместо списка имён: сколько игроков с каким результатом (в марафоне — ещё и лучшие по очкам).
function Distribution({ summary }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {summary.buckets.map((b) => (
          <Chip key={b.label} color={TONE_COLOR[b.tone]}>{b.label} · <b>{b.count}</b></Chip>
        ))}
      </div>
      {summary.top.length > 0 && (
        <div style={{ fontSize: 12, opacity: 0.8, marginTop: 6, overflowWrap: "anywhere" }}>
          Лучшие: {summary.top.map((t) => `${t.callsign} (${t.text.replace("все слова · ", "")})`).join(", ")}
        </div>
      )}
    </div>
  );
}

// Полный список результатов: поиск по позывному и сортировка; на телефоне — на весь экран.
function ResultsDialog({ title, results, onClose, isMobile }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("rank");
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const q = query.trim().toLowerCase();
  const rows = results.filter((r) => !q || r.callsign.toLowerCase().includes(q));
  if (sort === "time") rows.sort((a, b) => (b.at || "").localeCompare(a.at || "") || a.callsign.localeCompare(b.callsign));
  if (sort === "name") rows.sort((a, b) => a.callsign.localeCompare(b.callsign, "ru"));
  const clock = (r) => (r.at ? `${r.done ? "" : "с "}${formatClock(new Date(r.at))}` : "");

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 50, display: "flex", alignItems: isMobile ? "stretch" : "center", justifyContent: "center" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          ...panelStyle, display: "flex", flexDirection: "column", boxSizing: "border-box",
          width: isMobile ? "100%" : 560, maxHeight: isMobile ? "100%" : "80vh", borderRadius: isMobile ? 0 : undefined,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <div style={{ fontWeight: 700, overflowWrap: "anywhere" }}>{title} · {results.length}</div>
          <button onClick={onClose} style={{ ...ghostButtonStyle, ...touch(isMobile) }}>Закрыть</button>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
          <input
            value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск по позывному" autoFocus={!isMobile}
            style={{ flex: "1 1 160px", minWidth: 0, padding: "6px 10px", borderRadius: 6, border: "1px solid #3a3a3c", background: "#1a1a1c", color: "inherit", ...touch(isMobile) }}
          />
          <select
            value={sort} onChange={(e) => setSort(e.target.value)}
            style={{ padding: "6px 8px", borderRadius: 6, border: "1px solid #3a3a3c", background: "#1a1a1c", color: "inherit", ...touch(isMobile) }}
          >
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div style={{ overflowY: "auto", minHeight: 0 }}>
          {rows.length === 0 && <div style={{ opacity: 0.7, padding: "8px 0" }}>Никого не найдено.</div>}
          {rows.map((r) => (
            <div key={r.callsign} style={{ display: "flex", justifyContent: "space-between", gap: 10, padding: "6px 0", borderTop: "1px solid #2a2a2c", fontSize: 14 }}>
              <span style={{ overflowWrap: "anywhere" }}>{r.callsign}</span>
              <span style={{ display: "flex", gap: 10, flexShrink: 0, textAlign: "right" }}>
                <span style={{ color: r.done ? "#7dc778" : "#d9c36a" }}>{r.text}</span>
                <span style={{ opacity: 0.55, minWidth: 48 }}>{clock(r)}</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Card({ card, onOpen, onWordChange, isMobile }) {
  const { label } = useModes();
  const [showDialog, setShowDialog] = useState(false);
  const chips = card.results.slice(0, RESULTS_SHOWN);
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
          {card.summary ? (
            <Distribution summary={card.summary} />
          ) : (
            card.results.length > 0 && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                {chips.map((r) => (
                  <Chip key={r.callsign} color={r.done ? "#2f4d2c" : "#4d4326"}>{r.callsign} · {r.text}</Chip>
                ))}
              </div>
            )
          )}
          {card.results.length > 0 && (card.summary || card.results.length > RESULTS_SHOWN) && (
            <button onClick={() => setShowDialog(true)} style={{ ...ghostButtonStyle, ...touch(isMobile), marginTop: 8, fontSize: 12 }}>
              Все результаты ({card.results.length}) →
            </button>
          )}
        </div>
      )}

      {showDialog && <ResultsDialog title={card.title} results={card.results} onClose={() => setShowDialog(false)} isMobile={isMobile} />}

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
