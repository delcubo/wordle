import { Fragment, useEffect, useState } from "react";
import { api, ghostButtonStyle, panelStyle, tdStyle, thStyle, useLatest } from "../adminShared.jsx";
import { CopyButton, downloadCanvas } from "../exportUtils.jsx";

// Результаты командного тай-брейка: место команды, среднее по раундам, результаты игроков.
export function TiebreakTeamResultsPanel({ tournament, refreshKey }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(() => new Set());

  async function refresh() {
    const id = tournament.id;
    try {
      const res = await api(`/api/admin/tournaments/${id}/tiebreak-team-results`);
      if (tournamentIdRef.current === id) {
        setData(res);
        setError("");
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    setData(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id, tournament.teams_enabled, tournament.status, refreshKey]);

  if (!data) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  const cellText = (cell) => (!cell ? "-" : cell.solved ? `${cell.attempts_used}/6` : "X/6");
  const toggle = (id) => setExpanded((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  const NOTE = "Среднее число попыток команды в раунде; не угадал — 7, не завершил или не играл — 8";

  // Картинка таблицы: место, команда и среднее по каждому раунду — в том же стиле, что "Скачать" у
  // индивидуального тай-брейка (TiebreakResultsPanel). Команды, которые ещё не играли, не включаются.
  function handleDownload() {
    const rows = data.rows.filter((r) => r.place);
    const dpr = window.devicePixelRatio || 1;
    const font = "14px system-ui, sans-serif";
    const mctx = document.createElement("canvas").getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const nameCol = Math.max(120, ...rows.map((r) => mctx.measureText(r.name).width + 20));
    mctx.font = "bold 13px system-ui, sans-serif";
    const placeCol = Math.max(40, ...rows.map((r) => mctx.measureText(r.place).width + 16));
    mctx.font = "bold 11px system-ui, sans-serif";
    const roundCol = Math.max(70, ...data.rounds.map((r) => mctx.measureText(`Раунд ${r.round_number}`).width + 14));
    mctx.font = "12px system-ui, sans-serif";
    const noteWidth = mctx.measureText(NOTE).width;

    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const noteHeight = 26;
    const tableWidth = placeCol + nameCol + roundCol * data.rounds.length;
    const width = Math.max(tableWidth, noteWidth) + padding * 2;
    const height = headerHeight + rowHeight * rows.length + padding * 2 + noteHeight;

    const canvas = document.createElement("canvas");
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.textBaseline = "middle";

    const top = padding;
    const xName = padding + placeCol;
    const roundX = data.rounds.map((_, i) => xName + nameCol + roundCol * i);
    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, top, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Место", padding + placeCol / 2, top + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Команда", xName + 6, top + headerHeight / 2);
    ctx.font = "bold 11px system-ui, sans-serif";
    ctx.textAlign = "center";
    data.rounds.forEach((r, i) => ctx.fillText(`Раунд ${r.round_number}`, roundX[i] + roundCol / 2, top + headerHeight / 2));

    rows.forEach((r, ri) => {
      const y = top + headerHeight + ri * rowHeight;
      if (ri % 2 === 1) {
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(padding, y, tableWidth, rowHeight);
      }
      ctx.fillStyle = "#1a1a1b";
      ctx.font = "bold " + font;
      ctx.textAlign = "center";
      ctx.fillText(r.place, padding + placeCol / 2, y + rowHeight / 2);
      ctx.textAlign = "left";
      ctx.fillText(r.name, xName + 6, y + rowHeight / 2);
      ctx.textAlign = "center";
      r.cells.forEach((cell, i) => {
        ctx.fillStyle = cell ? "#1a1a1b" : "#999";
        ctx.font = cell ? "bold " + font : font;
        ctx.fillText(cell ? cell.average : "-", roundX[i] + roundCol / 2, y + rowHeight / 2);
      });
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let ri = 0; ri <= rows.length; ri++) {
      const y = top + headerHeight + ri * rowHeight;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + tableWidth, y);
      ctx.stroke();
    }
    ctx.fillStyle = "#666";
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(NOTE, padding, top + headerHeight + rowHeight * rows.length + 16);

    downloadCanvas(canvas, tournament.title, "_тайбрейк_команд");
  }

  function handleCopy() {
    const tags = [tournament.hashtag, "#тайбрейк_команд"].filter(Boolean).join(" ");
    const lines = data.rows
      .filter((r) => r.place)
      .map((r) => `${r.place} · ${r.name}${r.cells.some(Boolean) ? ` — ${r.cells.filter(Boolean).map((c) => c.average).join(" · ")}` : ""}`);
    const text = `${tags}\n\n${lines.join("\n")}\n\nсреднее число попыток команды по раундам; не угадал — 7, не завершил или не играл — 8`;
    return text;
  }

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>
          Результаты командного тай-брейка
          {data.last_place != null && (
            <span style={{ fontWeight: 400, fontSize: 13, opacity: 0.7 }}>
              {" "}· места {data.last_place > data.first_place ? `${data.first_place}–${data.last_place}` : data.first_place}
            </span>
          )}
        </h3>
        <div style={{ display: "flex", gap: 8 }}>
          {data.rounds.length > 0 && (
            <>
              <CopyButton getText={handleCopy} />
              <button onClick={handleDownload} style={ghostButtonStyle}>Скачать таблицу</button>
            </>
          )}
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      {data.rounds.length === 0 ? (
        <p style={{ opacity: 0.7, fontSize: 13, marginTop: 8 }}>Розыгрыш ещё не начался.</p>
      ) : (
        <>
          <p style={{ fontSize: 12, opacity: 0.65, marginTop: 6 }}>
            Среднее число попыток команды в раунде (не угадал — 7, не завершил или не играл — 8). Нажмите на команду, чтобы увидеть игроков.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
              <thead>
                <tr style={{ textAlign: "left", opacity: 0.7 }}>
                  <th style={thStyle}>Место</th>
                  <th style={thStyle}>Команда</th>
                  {data.rounds.map((r) => <th key={r.id} style={{ ...thStyle, textAlign: "center" }}>Раунд {r.round_number}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <Fragment key={row.team_id}>
                    <tr onClick={() => toggle(row.team_id)} style={{ borderTop: "1px solid #2a2a2c", cursor: "pointer" }}>
                      <td style={{ ...tdStyle, fontWeight: row.place && !row.place.includes("-") ? 700 : 400 }}>{row.place || "-"}</td>
                      <td style={tdStyle}>{expanded.has(row.team_id) ? "▾" : "▸"} {row.name}</td>
                      {row.cells.map((cell, i) => (
                        <td key={i} style={{ ...tdStyle, textAlign: "center", fontWeight: 700 }}>{cell ? cell.average : "-"}</td>
                      ))}
                    </tr>
                    {expanded.has(row.team_id) && row.members.map((m) => (
                      <tr key={m.entry_id} style={{ opacity: m.active ? 0.85 : 0.5, fontSize: 12 }}>
                        <td></td>
                        <td style={tdStyle}>{m.callsign}</td>
                        {m.cells.map((cell, i) => <td key={i} style={{ ...tdStyle, textAlign: "center" }}>{cellText(cell)}</td>)}
                      </tr>
                    ))}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}

export function TiebreakResultsPanel({ tournament, refreshKey }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const res = await api(`/api/admin/tournaments/${id}/tiebreak-results`);
      if (tournamentIdRef.current === id) setData(res);
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id, tournament.status, refreshKey]);

  if (!data) return null;

  function placeRank(place) {
    if (!place) return Infinity;
    return Number(place.split("-")[0]);
  }
  const rows = [...data.rows].sort((a, b) => placeRank(a.place) - placeRank(b.place) || a.callsign.localeCompare(b.callsign));

  function cellText(cell) {
    if (!cell) return "-";
    return cell.solved ? `${cell.attempts_used}/6` : "X/6";
  }

  function handleCopyTiebreak() {
    const tags = [tournament.hashtag, "#тайбрейк"].filter(Boolean).join(" ");
    const lines = rows
      .filter((r) => r.place)
      .map((r) => `${r.place} · ${r.callsign}${r.cells.some(Boolean) ? ` — ${r.cells.map(cellText).join(" · ")}` : ""}`);
    return `${tags}\n\n${lines.join("\n")}\n\nрезультаты по раундам; X — не угадал`;
  }

  // Картинка таблицы тай-брейка с раскладкой по раундам — тот же стиль
  // рисования, что и у "Скачать таблицу" в StandingsPanel (standard), только
  // колонки — раунды, а не дни (см. пункт бэклога).
  function handleDownloadTiebreak() {
    const dpr = window.devicePixelRatio || 1;
    const placeColMin = 40;
    const roundColMin = 50;
    const font = "14px system-ui, sans-serif";
    const measureCanvas = document.createElement("canvas");
    const mctx = measureCanvas.getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const callsignCol = Math.max(90, ...rows.map((r) => mctx.measureText(r.callsign).width + 20));
    mctx.font = "bold 13px system-ui, sans-serif";
    const placeCol = Math.max(placeColMin, ...rows.map((r) => mctx.measureText(r.place || "-").width + 16));
    mctx.font = "bold 11px system-ui, sans-serif";
    const roundCol = Math.max(
      roundColMin,
      ...data.rounds.map((r) => mctx.measureText(`Раунд ${r.round_number}`).width + 12)
    );

    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const tableWidth = placeCol + callsignCol + roundCol * data.rounds.length;
    const width = tableWidth + padding * 2;
    const height = headerHeight + rowHeight * rows.length + padding * 2;

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
    const roundX = [];
    for (let i = 0; i < data.rounds.length; i++) {
      roundX.push(x);
      x += roundCol;
    }

    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, tableTop, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Место", colX.place + placeCol / 2, tableTop + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Позывной", colX.callsign + 6, tableTop + headerHeight / 2);
    ctx.font = "bold 11px system-ui, sans-serif";
    ctx.textAlign = "center";
    data.rounds.forEach((r, i) => {
      ctx.fillText(`Раунд ${r.round_number}`, roundX[i] + roundCol / 2, tableTop + headerHeight / 2);
    });

    rows.forEach((r, ri) => {
      const rowY = tableTop + headerHeight + ri * rowHeight;
      if (ri % 2 === 1) {
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(padding, rowY, tableWidth, rowHeight);
      }
      ctx.fillStyle = "#1a1a1b";
      ctx.font = "bold " + font;
      ctx.textAlign = "center";
      ctx.fillText(r.place || "-", colX.place + placeCol / 2, rowY + rowHeight / 2);
      ctx.font = font;
      ctx.textAlign = "left";
      ctx.fillText(r.callsign, colX.callsign + 6, rowY + rowHeight / 2);
      ctx.textAlign = "center";
      r.cells.forEach((cell, i) => {
        ctx.fillStyle = cell ? "#1a1a1b" : "#999";
        ctx.fillText(cellText(cell), roundX[i] + roundCol / 2, rowY + rowHeight / 2);
      });
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let ri = 0; ri <= rows.length; ri++) {
      const y = tableTop + headerHeight + ri * rowHeight;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + tableWidth, y);
      ctx.stroke();
    }

    downloadCanvas(canvas, tournament.title, "_тайбрейк");
  }

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>
          Результаты тай-брейка
          {data.last_place != null && (
            <span style={{ fontWeight: 400, fontSize: 13, opacity: 0.7 }}>
              {" "}· места {data.last_place > data.first_place ? `${data.first_place}–${data.last_place}` : data.first_place}
            </span>
          )}
        </h3>
        <div style={{ display: "flex", gap: 8 }}>
          {data.rounds.length > 0 && (
            <>
              <CopyButton getText={handleCopyTiebreak} />
              <button onClick={handleDownloadTiebreak} style={ghostButtonStyle}>Скачать таблицу</button>
            </>
          )}
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      {data.rounds.length === 0 ? (
        <p style={{ opacity: 0.7, fontSize: 13, marginTop: 8 }}>Розыгрыш ещё не начался.</p>
      ) : (
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th style={thStyle}>Место</th>
                <th style={thStyle}>Позывной</th>
                {data.rounds.map((r) => (
                  <th key={r.id} style={thStyle} title={r.word}>Раунд {r.round_number}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.entry_id} style={{ borderTop: "1px solid #2a2a2c", opacity: row.active ? 1 : 0.5 }}>
                  <td style={{ ...tdStyle, fontWeight: row.place && !row.place.includes("-") ? 700 : 400 }}>{row.place || "-"}</td>
                  <td style={tdStyle}>{row.callsign}</td>
                  {row.cells.map((cell, i) => (
                    <td key={i} style={tdStyle}>{cellText(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}
