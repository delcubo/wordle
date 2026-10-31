import { useEffect, useState } from "react";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, tdStyle, thStyle, useLatest } from "../adminShared.jsx";
import { CopyButton, downloadCanvas } from "../exportUtils.jsx";
import { GuessesPopup } from "./GuessesPopup.jsx";
import { TieResolutionPanel, useTieResolution } from "./TieResolution.jsx";

// Янтарная подсветка бонусных очков (таблица на экране и в картинке)
const BONUS_BG = "rgba(229, 169, 76, 0.22)";

const BONUS_BG_PNG = "#fbe3b0";

// Подпись ячейки бонуса: сыгран — очки; доступен, но не сыгран — «·»; потерян/упущен — «—»; впереди — пусто
function bonusCellLabel(c) {
  if (!c) return "";
  if (c.state === "played") return String(c.points ?? 0);
  if (c.state === "open" || c.state === "pending") return "·";
  if (c.state === "lost" || c.state === "expired") return "—";
  return "";
}

const BONUS_STATE_TITLE = {
  played: "бонус сыгран",
  open: "бонус открыт, ещё не сыгран",
  pending: "бонус откроется после слова этого дня",
  upcoming: "бонус ещё впереди",
  future: "бонус ещё не вошёл в этот снимок",
  lost: "бонус потерян: в его блоке был пропуск",
  expired: "бонус не сыгран в день открытия",
};

export function StandingsPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [standings, setStandings] = useState(null);
  // "current" — live-таблица (включает сегодняшний день, если он уже сыгран);
  // число — снимок по состоянию на конкретный уже полностью прошедший день
  // (см. пункт бэклога: тогда копия/картинка тоже строится по этому снимку,
  // а не по live-данным, где не все успели сыграть сегодня).
  const [selectedDay, setSelectedDay] = useState("current");
  const [lastCompletedDay, setLastCompletedDay] = useState(0);
  const [editing, setEditing] = useState(null); // {participantId, day} | null
  const [form, setForm] = useState({ attempts_used: 1, solved: true, note: "" });
  const [error, setError] = useState("");
  const [hoveredCell, setHoveredCell] = useState(null); // {participantId, day} | null
  const [hoveredBonus, setHoveredBonus] = useState(null); // {participantId, number} | null
  const tie = useTieResolution(tournament.id, () => refresh());

  const placeLabel = (r) => `${r.place}${r.tie_resolved ? "*" : ""}`;
  // Пояснение под таблицей в копии и картинке, если есть места, определённые
  // тай-брейком (со звёздочкой)
  const TIE_FOOTNOTE = "* - по результатам тай-брейка";
  const hasTieResolved = () => standings.rows.some((r) => r.tie_resolved);

  function handleCopyStandings() {
    const tags = [standings.hashtag, "#таблица", `#д${standings.current_day}`].filter(Boolean).join(" ");
    // "·", а не "N. " — иначе Telegram распознаёт "1. " как начало
    // нумерованного списка и при вставке склеивает все строки в один пункт
    // (см. пункт бэклога)
    const lines = standings.rows.map((r) => `${placeLabel(r)} · ${r.callsign} — ${r.total_points}`);
    const text = `${tags}\n\n${lines.join("\n")}${hasTieResolved() ? `\n\n${TIE_FOOTNOTE}` : ""}`;
    return text;
  }

  function handleDownloadStandings() {
    const dpr = window.devicePixelRatio || 1;
    const dayCol = 34;
    const placeCol = 34;
    const totalCol = 54;
    const font = "14px system-ui, sans-serif";
    const measureCanvas = document.createElement("canvas");
    const mctx = measureCanvas.getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const callsignCol = Math.max(90, ...standings.rows.map((r) => mctx.measureText(r.callsign).width + 20));

    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const bonusCount = Math.max(0, ...standings.rows.map((r) => (r.bonus || []).length));
    const bonusCol = 34;
    const tableWidth = placeCol + callsignCol + totalCol + dayCol * standings.total_days + bonusCol * bonusCount;
    const footnotes = [];
    if (bonusCount > 0) footnotes.push("Бонусные слова (Б) выделены цветом");
    if (hasTieResolved()) footnotes.push(TIE_FOOTNOTE);
    const footnoteHeight = footnotes.length ? 8 + footnotes.length * 18 : 0;
    mctx.font = "12px system-ui, sans-serif";
    const footnoteWidth = footnotes.length ? Math.max(...footnotes.map((f) => mctx.measureText(f).width)) : 0;
    const width = Math.max(tableWidth, footnoteWidth) + padding * 2;
    const height = headerHeight + rowHeight * standings.rows.length + padding * 2 + footnoteHeight;

    const canvas = document.createElement("canvas");
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.textBaseline = "middle";

    const tableTop = padding;
    let x = padding;
    const colX = { place: x };
    x += placeCol;
    colX.callsign = x;
    x += callsignCol;
    colX.total = x;
    x += totalCol;
    const dayX = [];
    for (let i = 0; i < standings.total_days; i++) {
      dayX.push(x);
      x += dayCol;
    }
    const bonusX = [];
    for (let i = 0; i < bonusCount; i++) {
      bonusX.push(x);
      x += bonusCol;
    }

    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, tableTop, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("#", colX.place + placeCol / 2, tableTop + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Позывной", colX.callsign + 6, tableTop + headerHeight / 2);
    ctx.textAlign = "center";
    ctx.fillText("Σ", colX.total + totalCol / 2, tableTop + headerHeight / 2);
    for (let i = 0; i < standings.total_days; i++) {
      ctx.fillText(`${i + 1}`, dayX[i] + dayCol / 2, tableTop + headerHeight / 2);
    }
    for (let i = 0; i < bonusCount; i++) {
      ctx.fillStyle = BONUS_BG_PNG;
      ctx.fillRect(bonusX[i], tableTop, bonusCol, headerHeight);
      ctx.fillStyle = "#8a5a00";
      ctx.fillText(`Б${i + 1}`, bonusX[i] + bonusCol / 2, tableTop + headerHeight / 2);
    }

    standings.rows.forEach((r, ri) => {
      const rowY = tableTop + headerHeight + ri * rowHeight;
      if (ri % 2 === 1) {
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(padding, rowY, tableWidth, rowHeight);
      }
      ctx.fillStyle = "#1a1a1b";
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.fillText(placeLabel(r), colX.place + placeCol / 2, rowY + rowHeight / 2);
      ctx.textAlign = "left";
      ctx.fillText(r.callsign, colX.callsign + 6, rowY + rowHeight / 2);
      ctx.textAlign = "center";
      ctx.font = "bold " + font;
      ctx.fillText(String(r.total_points), colX.total + totalCol / 2, rowY + rowHeight / 2);
      ctx.font = font;
      r.daily.forEach((d, di) => {
        const label = d.played ? String(d.points) : (d.not_played_yet ? "—" : standings.skip_flag_symbol);
        ctx.fillStyle = d.played ? "#1a1a1b" : "#999";
        ctx.fillText(label, dayX[di] + dayCol / 2, rowY + rowHeight / 2);
      });
      (r.bonus || []).forEach((b, bi) => {
        const played = b.state === "played";
        if (played) {
          ctx.fillStyle = BONUS_BG_PNG;
          ctx.fillRect(bonusX[bi], rowY, bonusCol, rowHeight);
        }
        ctx.fillStyle = played ? "#5c3b00" : "#999";
        ctx.font = played ? "bold " + font : font;
        ctx.fillText(bonusCellLabel(b), bonusX[bi] + bonusCol / 2, rowY + rowHeight / 2);
        ctx.font = font;
      });
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let ri = 0; ri <= standings.rows.length; ri++) {
      const y = tableTop + headerHeight + ri * rowHeight;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + tableWidth, y);
      ctx.stroke();
    }

    if (footnoteHeight) {
      ctx.fillStyle = "#666";
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "left";
      footnotes.forEach((f, fi) => {
        ctx.fillText(f, padding, tableTop + headerHeight + rowHeight * standings.rows.length + 16 + fi * 18);
      });
    }

    downloadCanvas(canvas, tournament.title, "");
  }

  async function load(day) {
    const id = tournament.id;
    const qs = day === "current" ? "" : `?as_of_day=${day}`;
    const data = await api(`/api/admin/tournaments/${id}/standings${qs}`);
    if (tournamentIdRef.current === id) {
      setStandings(data);
      setLastCompletedDay(data.last_completed_day);
    }
  }

  // "Обновить" и обновление после ручной правки — перезагружают именно
  // выбранный сейчас день (live или снимок), не сбрасывая выбор.
  function refresh() {
    return load(selectedDay);
  }

  function handleDayChange(e) {
    const value = e.target.value;
    const day = value === "current" ? "current" : Number(value);
    setSelectedDay(day);
    setEditing(null);
    setError("");
    load(day);
  }

  useEffect(() => {
    setSelectedDay("current");
    load("current");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  if (!standings) return null;
  const bonusCount = Math.max(0, ...standings.rows.map((r) => (r.bonus || []).length));

  function startEdit(participantId, day, cell) {
    setError("");
    setEditing({ participantId, day });
    setForm({
      attempts_used: cell.played ? 1 : 1,
      solved: cell.played ? cell.points > 0 : true,
      note: "",
    });
  }

  async function handleSave() {
    setError("");
    try {
      await api(`/api/admin/entries/${editing.participantId}/days/${editing.day}/override`, {
        method: "POST",
        body: JSON.stringify({
          attempts_used: Number(form.attempts_used),
          solved: form.solved,
          note: form.note,
        }),
      });
      setEditing(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div style={{ ...panelStyle, marginTop: 20, overflowX: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ marginTop: 0 }}>Таблица</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={selectedDay} onChange={handleDayChange} style={{ ...inputStyle, padding: "4px 8px", fontSize: 13, width: "auto" }}>
            <option value="current">Текущий</option>
            {Array.from({ length: lastCompletedDay }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>День {d}</option>
            ))}
          </select>
          <CopyButton getText={handleCopyStandings} />
          <button onClick={handleDownloadStandings} style={ghostButtonStyle}>Скачать таблицу</button>
          {tournament.type === "standard" && selectedDay === "current"
            && standings.rows.some((r) => r.place.includes("-") || r.tie_resolved) && (
            <button onClick={tie.openTies} style={ghostButtonStyle}>Разобрать ничьи</button>
          )}
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      <p style={{ fontSize: 12, opacity: 0.6, marginTop: -4 }}>
        {selectedDay !== "current" && `Показан снимок таблицы по состоянию на конец дня ${selectedDay}. `}
        Клик по ячейке дня — ручная корректировка результата (исключительные случаи). Наведите на цифру — покажутся попытки этого дня.
        {bonusCount > 0 && " Столбцы Б — бонусные слова (янтарным выделены сыгранные, их очки входят в Σ): · — доступен, но не сыгран, — — потерян или упущен."}
      </p>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}
      {tie.open && <TieResolutionPanel tie={tie} />}
      <table style={{ borderCollapse: "collapse", fontSize: 13, minWidth: 400 }}>
        <thead>
          <tr>
            <th style={thStyle}>#</th>
            <th style={thStyle}>Позывной</th>
            <th style={thStyle}>Σ</th>
            {Array.from({ length: standings.total_days }, (_, i) => (
              <th key={i} style={thStyle}>#{i + 1}</th>
            ))}
            {Array.from({ length: bonusCount }, (_, i) => (
              <th key={`b${i}`} style={{ ...thStyle, background: BONUS_BG }} title={`Бонусное слово ${i + 1}`}>Б{i + 1}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {standings.rows.map((r) => (
            <tr key={r.participant_id} style={{ borderTop: "1px solid #2a2a2c" }}>
              <td style={tdStyle}>{placeLabel(r)}</td>
              <td style={tdStyle}>{r.callsign}</td>
              <td style={{ ...tdStyle, fontWeight: 700 }}>{r.total_points}</td>
              {r.daily.map((d, i) => {
                const day = i + 1;
                const isEditing = editing?.participantId === r.participant_id && editing?.day === day;
                if (isEditing) {
                  return (
                    <td key={i} style={{ ...tdStyle, background: "#2a2a2c" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 140 }}>
                        <input
                          type="number" min={1} max={6} value={form.attempts_used}
                          onChange={(e) => setForm((f) => ({ ...f, attempts_used: e.target.value }))}
                          style={{ ...inputStyle, padding: "2px 6px", fontSize: 12 }}
                          placeholder="Попыток"
                        />
                        <label style={{ fontSize: 11, display: "flex", gap: 4, alignItems: "center" }}>
                          <input
                            type="checkbox" checked={form.solved}
                            onChange={(e) => setForm((f) => ({ ...f, solved: e.target.checked }))}
                          />
                          угадал
                        </label>
                        <input
                          placeholder="Причина (обязательно)" value={form.note}
                          onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                          style={{ ...inputStyle, padding: "2px 6px", fontSize: 12 }}
                        />
                        <div style={{ display: "flex", gap: 4 }}>
                          <button onClick={handleSave} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
                          <button onClick={() => setEditing(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
                        </div>
                      </div>
                    </td>
                  );
                }
                const isHovered = hoveredCell?.participantId === r.participant_id && hoveredCell?.day === day;
                return (
                  <td
                    key={i}
                    onClick={() => startEdit(r.participant_id, day, d)}
                    onMouseEnter={() => { if (d.guesses?.length > 0) setHoveredCell({ participantId: r.participant_id, day }); }}
                    onMouseLeave={() => setHoveredCell(null)}
                    title={d.admin_note ? `Скорректировано: ${d.admin_note}` : "Клик — скорректировать"}
                    style={{ ...tdStyle, textAlign: "center", cursor: "pointer", position: "relative" }}
                  >
                    {d.played ? d.points : (d.not_played_yet ? "—" : standings.skip_flag_symbol)}
                    {d.admin_note && <sup style={{ color: "#e5a94c" }}>✎</sup>}
                    {isHovered && (
                      <div
                        style={{
                          position: "absolute", bottom: "100%", left: "50%", transform: "translateX(-50%)",
                          background: "#1c1c1e", border: "1px solid #3a3a3c", borderRadius: 6, padding: "6px 10px",
                          whiteSpace: "nowrap", zIndex: 10, marginBottom: 4, textAlign: "left", pointerEvents: "none",
                        }}
                      >
                        {d.guesses.map((g, gi) => (
                          <div key={gi} style={{ fontFamily: "monospace", fontSize: 13, letterSpacing: 1, textTransform: "uppercase" }}>
                            {g}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                );
              })}
              {(r.bonus || []).map((b) => {
                const hovered = hoveredBonus?.participantId === r.participant_id && hoveredBonus?.number === b.number;
                return (
                  <td
                    key={`b${b.number}`}
                    title={`Б${b.number} (день ${b.opening_day}): ${BONUS_STATE_TITLE[b.state] || b.state}`}
                    onMouseEnter={() => { if (b.guesses?.length > 0) setHoveredBonus({ participantId: r.participant_id, number: b.number }); }}
                    onMouseLeave={() => setHoveredBonus(null)}
                    style={{
                      ...tdStyle, textAlign: "center", position: "relative",
                      background: b.state === "played" ? BONUS_BG : "transparent",
                      fontWeight: b.state === "played" ? 700 : 400,
                      opacity: b.state === "played" || b.state === "open" || b.state === "pending" ? 1 : 0.5,
                    }}
                  >
                    {bonusCellLabel(b)}
                    {hovered && <GuessesPopup guesses={b.guesses} heading={`Бонус ${b.number}`} />}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
