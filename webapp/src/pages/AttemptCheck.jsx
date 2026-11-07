import { useEffect, useState } from "react";
import { api, panelStyle, ghostButtonStyle } from "./adminShared.jsx";

const TONE = {
  ok: { mark: "✓", color: "#7dc778" },
  warn: { mark: "⚠", color: "#e5a94c" },
  info: { mark: "•", color: "#9a9a9e" },
};
const dm = (iso) => iso.split("-").reverse().slice(0, 2).join(".");
const clock = (iso) => new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

// «через 14 мин», «через 3 ч 05 м» — сколько прошло от публикации слова до результата
function span(seconds) {
  if (seconds == null) return "";
  if (seconds < 60) return `${Math.max(seconds, 0)} с`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h} ч ${String(m).padStart(2, "0")} м` : `${m} мин`;
}

function Section({ title, count, open = false, children }) {
  return (
    <details open={open} style={{ borderTop: "1px solid #2a2a2c", padding: "8px 0" }}>
      <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
        {title}{count != null && <span style={{ opacity: 0.6, fontWeight: 400 }}> · {count}</span>}
      </summary>
      <div style={{ marginTop: 6, fontSize: 13 }}>{children}</div>
    </details>
  );
}

const Muted = ({ children }) => <div style={{ opacity: 0.6 }}>{children}</div>;

// Окно «Проверка»: факты по результату игрока (чаще всего — «1/6»); вывод делает админ.
export default function AttemptCheckDialog({ entryId, wordId, onClose, isMobile }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api(`/api/admin/entries/${entryId}/attempt-check?word_id=${wordId}`)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [entryId, wordId]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      onClick={(e) => { e.stopPropagation(); onClose(); }}   // не закрывать вместе с ним окно результатов под ним
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 60, display: "flex", alignItems: isMobile ? "stretch" : "center", justifyContent: "center" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          ...panelStyle, display: "flex", flexDirection: "column", boxSizing: "border-box",
          width: isMobile ? "100%" : 600, maxHeight: isMobile ? "100%" : "86vh", borderRadius: isMobile ? 0 : undefined,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8, marginBottom: 8 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, overflowWrap: "anywhere" }}>Проверка · {data ? data.callsign : "…"}</div>
            {data && (
              <div style={{ fontSize: 12, opacity: 0.7, marginTop: 2, overflowWrap: "anywhere" }}>
                {data.tournament} · {data.day_label} · {dm(data.date)}
                {data.player_note ? ` · ${data.player_note}` : ""}
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ ...ghostButtonStyle, flexShrink: 0, ...(isMobile ? { minHeight: 40 } : {}) }}>Закрыть</button>
        </div>

        {error && <div style={{ color: "#e5484d" }}>{error}</div>}
        {!data && !error && <div style={{ opacity: 0.7 }}>Загрузка…</div>}

        {data && (
          <div style={{ overflowY: "auto", minHeight: 0 }}>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "flex-start", marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 12, opacity: 0.6 }}>слово</div>
                <div style={{ fontSize: 20, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2 }}>{data.word}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, opacity: 0.6 }}>
                  {data.solved ? `угадал с ${data.guessed_in}-й попытки` : "не угадал"}
                </div>
                {data.guesses.map((g, i) => (
                  <div key={i} style={{ fontFamily: "monospace", fontSize: 14, letterSpacing: 1, textTransform: "uppercase", opacity: g === data.word ? 1 : 0.75 }}>
                    {g}
                  </div>
                ))}
                {data.guesses.length === 0 && <Muted>попытки не сохранены</Muted>}
              </div>
              {data.finished_at && (
                <div style={{ fontSize: 13 }}>
                  <div style={{ fontSize: 12, opacity: 0.6 }}>закончил</div>
                  {clock(data.finished_at)}
                  {data.seconds_after_publish != null && data.seconds_after_publish >= 0 && (
                    <span style={{ opacity: 0.7 }}> · через {span(data.seconds_after_publish)} после публикации слова</span>
                  )}
                  <div style={{ opacity: 0.7 }}>{data.rank}-й из {data.finished_total} закончивших</div>
                </div>
              )}
            </div>

            {data.manual && <div style={{ color: "#e5a94c", fontSize: 13, marginBottom: 8 }}>✎ Результат выставлен админом вручную — попыток и времени игрока нет.</div>}

            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
              {data.signals.map((s, i) => (
                <div key={i} style={{ display: "flex", gap: 8, fontSize: 14 }}>
                  <span style={{ color: TONE[s.tone].color, width: 16, flexShrink: 0 }}>{TONE[s.tone].mark}</span>
                  <span style={{ overflowWrap: "anywhere" }}>{s.text}</span>
                </div>
              ))}
            </div>

            <Section title="Где игрок вводил это слово" count={data.history_total} open={data.history.length > 0}>
              {data.history.length === 0 && <Muted>Нигде, кроме этого дня.</Muted>}
              {data.history.map((h, i) => (
                <div key={i} style={{ padding: "2px 0", overflowWrap: "anywhere" }}>
                  {dm(h.date)} · {h.tournament} · {h.label} · <b>{h.position}-й попыткой</b>
                  {h.was_answer && <span style={{ opacity: 0.7 }}> (было ответом)</span>}
                  {!h.earlier && <span style={{ opacity: 0.6 }}> · позже этого дня</span>}
                </div>
              ))}
            </Section>

            <Section title="Обычные первые слова игрока" count={data.openers_games ? `${data.openers_games} игр` : null}>
              {data.openers.length === 0 && <Muted>Других игр пока нет.</Muted>}
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {data.openers.map((o) => (
                  <span key={o.word} style={{ padding: "2px 8px", borderRadius: 4, background: o.word === data.word.toLowerCase() ? "#2f4d2c" : "#3a3a3c", textTransform: "uppercase" }}>
                    {o.word} · {o.count}
                  </span>
                ))}
              </div>
            </Section>

            <Section title="Проиграли до него (видели ответ)" count={data.failed_before.length} open={data.failed_before.length > 0}>
              {data.failed_before.length === 0 && <Muted>Никто. Угадали раньше: {data.solved_before}.</Muted>}
              {data.failed_before.map((f, i) => (
                <div key={i} style={{ padding: "2px 0" }}>{f.callsign} · {clock(f.at)}</div>
              ))}
            </Section>

            {data.other_tournaments.length > 0 && (
              <Section title="Это же слово в других розыгрышах (±1 день)" count={data.other_tournaments.length} open>
                {data.other_tournaments.map((o, i) => (
                  <div key={i} style={{ padding: "2px 0", overflowWrap: "anywhere" }}>
                    {dm(o.date)} · {o.tournament} · {o.label} ·{" "}
                    {o.played ? <>игрок сыграл{o.result ? ` ${o.result}` : ""}{o.finished_before ? " — раньше, чем здесь" : ""}</> : "игрок там не играл"}
                  </div>
                ))}
              </Section>
            )}

            <Section title="Статистика «1/6»">
              <div>
                У игрока: <b>{data.stats.player_first}</b> из {data.stats.player_games}
                {" · "}у остальных: <b>{data.stats.rest_first}</b> из {data.stats.rest_games}
              </div>
              <Muted>Считаются только законченные игры без ручных корректировок.</Muted>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}
