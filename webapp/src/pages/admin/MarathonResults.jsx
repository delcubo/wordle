import { Fragment, useEffect, useState } from "react";
import { api, ghostButtonStyle, inputStyle, panelStyle, tdStyle, thStyle, useLatest } from "../adminShared.jsx";
import { CopyButton, downloadCanvas } from "../exportUtils.jsx";
import { GuessesPopup } from "./GuessesPopup.jsx";
import { TieResolutionPanel, useTieResolution } from "./TieResolution.jsx";

function marathonCellLabel(c) {
  if (!c) return "·"; // ещё не дошёл
  if (!c.finished) return "…"; // слово начато, не закончено
  return c.solved ? String(c.attempts_used) : "X";
}

export function MarathonStandingsPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [hoveredCell, setHoveredCell] = useState(null); // {entryId, index} | null — показ попыток
  const tie = useTieResolution(tournament.id, () => refresh());
  const placeLabel = (r) => `${r.place}${r.tie_resolved ? "*" : ""}`;
  // Пояснение под таблицей в копии и картинке, если есть места, определённые тай-брейком
  const TIE_FOOTNOTE = "* - по результатам тай-брейка";
  const hasTieResolved = () => data.rows.some((r) => r.tie_resolved);

  async function refresh() {
    const id = tournament.id;
    try {
      const res = await api(`/api/admin/tournaments/${id}/marathon/standings`);
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
  }, [tournament.id, tournament.words_count]);

  const RULE_NOTE = (d) => `Неугаданное слово = ${d.unsolved_attempts} попыток, пропущенное (не пройденное) = ${d.skipped_attempts}`;

  function handleCopy() {
    const tags = [data.hashtag, "#таблица"].filter(Boolean).join(" ");
    // "·", а не "N. " — иначе Telegram склеивает строки в нумерованный список
    const lines = data.rows.map((r) => `${placeLabel(r)} · ${r.callsign} — ${r.score} (${r.words_done}/${data.words_count})`);
    const text = `${tags}\n\n${lines.join("\n")}\n\nпопыток всего (слов пройдено/всего). ${RULE_NOTE(data)}${hasTieResolved() ? `\n${TIE_FOOTNOTE}` : ""}`;
    return text;
  }

  function handleDownload() {
    const dpr = window.devicePixelRatio || 1;
    const placeCol = 40;
    const wordCol = 32;
    const doneCol = 56;
    const totalCol = 66;
    const font = "14px system-ui, sans-serif";
    const mctx = document.createElement("canvas").getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const callsignCol = Math.max(90, ...data.rows.map((r) => mctx.measureText(r.callsign).width + 20));
    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const noteHeight = 26 + (hasTieResolved() ? 18 : 0);
    const tableWidth = placeCol + callsignCol + wordCol * data.words_count + doneCol + totalCol;
    mctx.font = "12px system-ui, sans-serif";
    const noteWidth = mctx.measureText(RULE_NOTE(data)).width;
    const width = Math.max(tableWidth, noteWidth) + padding * 2;
    const height = headerHeight + rowHeight * data.rows.length + padding * 2 + noteHeight;

    const canvas = document.createElement("canvas");
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.textBaseline = "middle";

    const top = padding;
    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, top, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    const xPlace = padding;
    const xCallsign = xPlace + placeCol;
    const xWords = xCallsign + callsignCol;
    const xDone = xWords + wordCol * data.words_count;
    const xTotal = xDone + doneCol;
    ctx.textAlign = "center";
    ctx.fillText("#", xPlace + placeCol / 2, top + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Позывной", xCallsign + 6, top + headerHeight / 2);
    ctx.textAlign = "center";
    for (let i = 0; i < data.words_count; i++) ctx.fillText(String(i + 1), xWords + wordCol * i + wordCol / 2, top + headerHeight / 2);
    ctx.fillText("Слов", xDone + doneCol / 2, top + headerHeight / 2);
    ctx.fillText("Попыток", xTotal + totalCol / 2, top + headerHeight / 2);

    data.rows.forEach((r, ri) => {
      const y = top + headerHeight + ri * rowHeight;
      if (ri % 2 === 1) {
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(padding, y, tableWidth, rowHeight);
      }
      ctx.fillStyle = "#1a1a1b";
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.fillText(placeLabel(r), xPlace + placeCol / 2, y + rowHeight / 2);
      ctx.textAlign = "left";
      ctx.fillText(r.callsign, xCallsign + 6, y + rowHeight / 2);
      ctx.textAlign = "center";
      r.cells.forEach((c, ci) => {
        ctx.fillStyle = c && c.finished ? "#1a1a1b" : "#999";
        ctx.fillText(marathonCellLabel(c), xWords + wordCol * ci + wordCol / 2, y + rowHeight / 2);
      });
      ctx.fillStyle = "#1a1a1b";
      ctx.fillText(`${r.words_done}/${data.words_count}`, xDone + doneCol / 2, y + rowHeight / 2);
      ctx.font = "bold " + font;
      ctx.fillText(String(r.score), xTotal + totalCol / 2, y + rowHeight / 2);
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let ri = 0; ri <= data.rows.length; ri++) {
      const y = top + headerHeight + ri * rowHeight;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + tableWidth, y);
      ctx.stroke();
    }
    ctx.fillStyle = "#666";
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(RULE_NOTE(data), padding, top + headerHeight + rowHeight * data.rows.length + 16);
    if (hasTieResolved()) ctx.fillText(TIE_FOOTNOTE, padding, top + headerHeight + rowHeight * data.rows.length + 34);

    downloadCanvas(canvas, tournament.title, "");
  }

  if (!data) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Таблица марафона</h3>
        <div style={{ display: "flex", gap: 8 }}>
          {data.rows.length > 0 && (
            <>
              <CopyButton getText={handleCopy} />
              <button onClick={handleDownload} style={ghostButtonStyle}>Скачать таблицу</button>
              {data.rows.some((r) => r.place.includes("-") || r.tie_resolved) && (
                <button onClick={tie.openTies} style={ghostButtonStyle}>Разобрать ничьи</button>
              )}
            </>
          )}
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      <p style={{ fontSize: 12, opacity: 0.65, marginTop: 6 }}>
        Место — по сумме попыток: угадал — число попыток, не угадал — {data.unsolved_attempts}, не пройденное слово — {data.skipped_attempts}.
        При равенстве выше тот, у кого меньше пропущенных слов, затем меньше неугаданных.
        В ячейках: число попыток, X — не угадано, … — слово начато, · — ещё не дошёл.
      </p>
      {tie.open && <TieResolutionPanel tie={tie} />}
      {data.rows.length === 0 ? (
        <div style={{ opacity: 0.7, fontSize: 13 }}>Пока никто не начал играть.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th style={thStyle}>Место</th>
                <th style={thStyle}>Позывной</th>
                {data.words.map((w) => (
                  <th key={w.day_number} style={{ ...thStyle, textAlign: "center" }} title={w.word || undefined}>{w.day_number}</th>
                ))}
                <th style={{ ...thStyle, textAlign: "center" }}>Слов</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Попыток</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.entry_id} style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={{ ...tdStyle, fontWeight: r.place && !r.place.includes("-") ? 700 : 400 }}>{placeLabel(r)}</td>
                  <td style={tdStyle}>{r.callsign}</td>
                  {r.cells.map((c, i) => (
                    <td
                      key={i}
                      title={c && c.word && !(c.guesses && c.guesses.length > 0) ? c.word.toUpperCase() : undefined}
                      onMouseEnter={() => { if (c && c.guesses && c.guesses.length > 0) setHoveredCell({ entryId: r.entry_id, index: i }); }}
                      onMouseLeave={() => setHoveredCell(null)}
                      style={{ ...tdStyle, textAlign: "center", opacity: c && c.finished ? 1 : 0.5, position: "relative" }}
                    >
                      {marathonCellLabel(c)}
                      {hoveredCell && hoveredCell.entryId === r.entry_id && hoveredCell.index === i && (
                        <GuessesPopup guesses={c.guesses} heading={c.word || undefined} />
                      )}
                    </td>
                  ))}
                  <td style={{ ...tdStyle, textAlign: "center" }}>{r.words_done}/{data.words_count}</td>
                  <td style={{ ...tdStyle, textAlign: "center", fontWeight: 700 }}>{r.score}</td>
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

// Командная таблица марафона: среднее число попыток на слово (api/teams.py).
export function MarathonTeamStandingsPanel({ tournament, refreshKey, tournaments = [], onTournamentsChanged }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(() => new Set());
  const [tbDate, setTbDate] = useState(""); // дата старта создаваемого тай-брейка; пусто — сегодня
  const [tbMessage, setTbMessage] = useState("");
  const [tbBusy, setTbBusy] = useState(false);
  const todayIso = new Date().toISOString().slice(0, 10);

  // Командный тай-брейк для группы команд с общим местом: новый розыгрыш с теми же командами и игроками
  async function createTiebreak(place) {
    setTbBusy(true);
    setTbMessage("");
    try {
      const created = await api(`/api/admin/tournaments/${tournament.id}/team-tie-groups/create-tiebreak`, {
        method: "POST", body: JSON.stringify({ place, start_date: tbDate || null }),
      });
      setTbMessage(`Создан тай-брейк «${created.title}» (старт ${created.start_date}). Он в списке розыгрышей слева; игроки играют по своим обычным ссылкам.`);
      if (onTournamentsChanged) await onTournamentsChanged();
      await tie.openTies();
    } catch (e) {
      setTbMessage(e.message);
    } finally {
      setTbBusy(false);
    }
  }

  const tie = useTieResolution(tournament.id, () => refresh(), {
    groupsPath: "team-tie-groups", savePath: "team-tie-resolutions", idKey: "team_id", idsKey: "team_ids", nameKey: "name",
    renderGroupExtra: (g) => {
      if (g.tiebreak_id != null) {
        const tb = tournaments.find((t) => t.id === g.tiebreak_id);
        return (
          <span style={{ fontSize: 12, opacity: 0.8 }}>
            Тай-брейк команд создан{tb ? `: «${tb.title}»` : ` (розыгрыш №${g.tiebreak_id})`}
          </span>
        );
      }
      return (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="date" min={todayIso} value={tbDate} onChange={(e) => setTbDate(e.target.value)}
            title="Дата старта тай-брейка (пусто — сегодня)"
            style={{ ...inputStyle, padding: "2px 6px", fontSize: 12, width: "auto" }}
          />
          <button
            onClick={() => createTiebreak(g.place)} disabled={tbBusy}
            style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 12, opacity: tbBusy ? 0.6 : 1 }}
          >
            Создать тай-брейк для этих команд
          </button>
        </div>
      );
    },
  });
  const placeLabel = (r) => `${r.place}${r.tie_resolved ? "*" : ""}`;
  const TIE_FOOTNOTE = "* - место определено разбором ничьей";
  const RULE_NOTE = (d) => `Среднее число попыток на слово; неугаданное слово = ${d.unsolved_attempts}, непройденное = ${d.skipped_attempts}`;

  async function refresh() {
    const id = tournament.id;
    try {
      const res = await api(`/api/admin/tournaments/${id}/marathon/team-standings`);
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
  }, [tournament.id, tournament.words_count, refreshKey]);

  // Игроки команды — от лучшего среднего к худшему
  const sortedMembers = (r) => [...r.members].sort(
    (a, b) => a.average_value - b.average_value || a.callsign.localeCompare(b.callsign, "ru")
  );
  const DETAIL_NOTE = `Среднее игрока = (попытки + ${data?.skipped_attempts ?? 8} × непройденные слова) ÷ слов; среднее команды — среднее по её игрокам`;
  const CELLS_LEGEND = `X — не угадано (= ${data?.unsolved_attempts ?? 7}), … — слово начато, · — ещё не дошёл (непройденное = ${data?.skipped_attempts ?? 8})`;
  const MAX_DETAIL_CELLS = 12; // при большем числе слов результаты по словам в картинку не рисуем

  function handleCopyDetailed() {
    const tags = [data.hashtag, "#командный_зачёт"].filter(Boolean).join(" ");
    const hasTie = data.rows.some((r) => r.tie_resolved);
    const blocks = data.rows.map((r) => [
      `${placeLabel(r)} · ${r.name} — ${r.average} (${r.words_done}/${r.words_total} слов)`,
      ...sortedMembers(r).map((m) => `  ${m.callsign} — ${m.average} · ${m.cells.map(marathonCellLabel).join(" ")}`),
    ].join("\n"));
    const text = `${tags}\n\n${blocks.join("\n")}\n\nсреднее число попыток на слово; X — не угадано, · — ещё не дошёл; неугаданное слово = ${data.unsolved_attempts}, непройденное = ${data.skipped_attempts}${hasTie ? `\n${TIE_FOOTNOTE}` : ""}`;
    return text;
  }

  // Подробная картинка: по блоку на команду — строка команды (итоги и среднее) и под ней строки её
  // игроков (результаты по словам, попытки, непройденные слова, среднее игрока).
  function handleDownloadDetailed() {
    const withCells = data.words_count <= MAX_DETAIL_CELLS;
    const hasTie = data.rows.some((r) => r.tie_resolved);
    const dpr = window.devicePixelRatio || 1;
    const placeCol = 40;
    const wordCol = 32;
    const doneCol = 56;
    const attCol = 66;
    const unplCol = 88;
    const avgCol = 76;
    const indent = 18;
    const font = "14px system-ui, sans-serif";
    const mctx = document.createElement("canvas").getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const teamW = Math.max(0, ...data.rows.map((r) => mctx.measureText(r.name).width));
    mctx.font = "13px system-ui, sans-serif";
    const playerW = Math.max(0, ...data.rows.flatMap((r) => r.members.map((m) => mctx.measureText(m.callsign + (m.active ? "" : " (откл.)")).width + indent)));
    const nameCol = Math.max(150, teamW + 20, playerW + 20);
    const cellsW = withCells ? wordCol * data.words_count : 0;
    const tableWidth = placeCol + nameCol + cellsW + doneCol + attCol + unplCol + avgCol;

    const notes = [DETAIL_NOTE];
    if (withCells) notes.push(CELLS_LEGEND);
    if (hasTie) notes.push(TIE_FOOTNOTE);
    mctx.font = "12px system-ui, sans-serif";
    const noteWidth = Math.max(...notes.map((n) => mctx.measureText(n).width));

    const items = [];
    data.rows.forEach((r) => {
      items.push({ team: r });
      sortedMembers(r).forEach((m) => items.push({ member: m }));
    });
    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const noteHeight = 10 + notes.length * 18;
    const width = Math.max(tableWidth, noteWidth) + padding * 2;
    const height = headerHeight + rowHeight * items.length + padding * 2 + noteHeight;

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
    const xCells = xName + nameCol;
    const xDone = xCells + cellsW;
    const xAtt = xDone + doneCol;
    const xUnpl = xAtt + attCol;
    const xAvg = xUnpl + unplCol;
    const mid = (y) => y + rowHeight / 2;

    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, top, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("#", padding + placeCol / 2, top + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Команда / игрок", xName + 6, top + headerHeight / 2);
    ctx.textAlign = "center";
    if (withCells) for (let i = 0; i < data.words_count; i++) ctx.fillText(String(i + 1), xCells + wordCol * i + wordCol / 2, top + headerHeight / 2);
    ctx.fillText("Слов", xDone + doneCol / 2, top + headerHeight / 2);
    ctx.fillText("Попыток", xAtt + attCol / 2, top + headerHeight / 2);
    ctx.fillText("Не сыграно", xUnpl + unplCol / 2, top + headerHeight / 2);
    ctx.fillText("Среднее", xAvg + avgCol / 2, top + headerHeight / 2);

    items.forEach((item, i) => {
      const y = top + headerHeight + i * rowHeight;
      if (item.team) {
        const r = item.team;
        ctx.fillStyle = "#e8edf4";
        ctx.fillRect(padding, y, tableWidth, rowHeight);
        ctx.fillStyle = "#1a1a1b";
        ctx.font = "bold " + font;
        ctx.textAlign = "center";
        ctx.fillText(placeLabel(r), padding + placeCol / 2, mid(y));
        ctx.textAlign = "left";
        ctx.fillText(r.name, xName + 6, mid(y));
        ctx.textAlign = "center";
        ctx.fillText(`${r.words_done}/${r.words_total}`, xDone + doneCol / 2, mid(y));
        ctx.fillText(String(r.attempts_sum), xAtt + attCol / 2, mid(y));
        ctx.fillText(String(r.unplayed_words), xUnpl + unplCol / 2, mid(y));
        ctx.fillText(r.average, xAvg + avgCol / 2, mid(y));
      } else {
        const m = item.member;
        ctx.fillStyle = m.active ? "#333" : "#999";
        ctx.font = "13px system-ui, sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(m.callsign + (m.active ? "" : " (откл.)"), xName + 6 + indent, mid(y));
        ctx.textAlign = "center";
        if (withCells) {
          m.cells.forEach((c, ci) => {
            ctx.fillStyle = c && c.finished ? "#1a1a1b" : "#999";
            ctx.fillText(marathonCellLabel(c), xCells + wordCol * ci + wordCol / 2, mid(y));
          });
        }
        ctx.fillStyle = m.active ? "#333" : "#999";
        ctx.fillText(`${m.words_done}/${data.words_count}`, xDone + doneCol / 2, mid(y));
        ctx.fillText(String(m.total_attempts), xAtt + attCol / 2, mid(y));
        ctx.fillText(String(m.unplayed_words), xUnpl + unplCol / 2, mid(y));
        ctx.font = "bold 13px system-ui, sans-serif";
        ctx.fillText(m.average, xAvg + avgCol / 2, mid(y));
      }
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let i = 0; i <= items.length; i++) {
      const y = top + headerHeight + i * rowHeight;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + tableWidth, y);
      ctx.stroke();
    }
    ctx.fillStyle = "#666";
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "left";
    notes.forEach((n, i) => ctx.fillText(n, padding, top + headerHeight + rowHeight * items.length + 16 + i * 18));

    downloadCanvas(canvas, tournament.title, "_команды_подробно");
  }

  function toggleExpanded(id) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleCopy() {
    const tags = [data.hashtag, "#командный_зачёт"].filter(Boolean).join(" ");
    // "·", а не "N. " — иначе Telegram склеивает строки в нумерованный список
    const lines = data.rows.map((r) => `${placeLabel(r)} · ${r.name} — ${r.average} (${r.words_done}/${r.words_total})`);
    const hasTie = data.rows.some((r) => r.tie_resolved);
    const text = `${tags}\n\n${lines.join("\n")}\n\nсреднее число попыток на слово (слов пройдено/всего). Неугаданное слово = ${data.unsolved_attempts}, непройденное = ${data.skipped_attempts}${hasTie ? `\n${TIE_FOOTNOTE}` : ""}`;
    return text;
  }

  function handleDownload() {
    const dpr = window.devicePixelRatio || 1;
    const placeCol = 40;
    const sizeCol = 70;
    const doneCol = 70;
    const avgCol = 80;
    const font = "14px system-ui, sans-serif";
    const mctx = document.createElement("canvas").getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const nameCol = Math.max(120, ...data.rows.map((r) => mctx.measureText(r.name).width + 20));
    const hasTie = data.rows.some((r) => r.tie_resolved);
    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const noteHeight = 26 + (hasTie ? 18 : 0);
    const tableWidth = placeCol + nameCol + sizeCol + doneCol + avgCol;
    mctx.font = "12px system-ui, sans-serif";
    const noteWidth = mctx.measureText(RULE_NOTE(data)).width;
    const width = Math.max(tableWidth, noteWidth) + padding * 2;
    const height = headerHeight + rowHeight * data.rows.length + padding * 2 + noteHeight;

    const canvas = document.createElement("canvas");
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.textBaseline = "middle";

    const top = padding;
    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, top, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    const xName = padding + placeCol;
    const xSize = xName + nameCol;
    const xDone = xSize + sizeCol;
    const xAvg = xDone + doneCol;
    ctx.textAlign = "center";
    ctx.fillText("#", padding + placeCol / 2, top + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Команда", xName + 6, top + headerHeight / 2);
    ctx.textAlign = "center";
    ctx.fillText("Игроков", xSize + sizeCol / 2, top + headerHeight / 2);
    ctx.fillText("Слов", xDone + doneCol / 2, top + headerHeight / 2);
    ctx.fillText("Среднее", xAvg + avgCol / 2, top + headerHeight / 2);

    data.rows.forEach((r, ri) => {
      const y = top + headerHeight + ri * rowHeight;
      if (ri % 2 === 1) {
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(padding, y, tableWidth, rowHeight);
      }
      ctx.fillStyle = "#1a1a1b";
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.fillText(placeLabel(r), padding + placeCol / 2, y + rowHeight / 2);
      ctx.textAlign = "left";
      ctx.fillText(r.name, xName + 6, y + rowHeight / 2);
      ctx.textAlign = "center";
      ctx.fillText(String(r.members_count), xSize + sizeCol / 2, y + rowHeight / 2);
      ctx.fillText(`${r.words_done}/${r.words_total}`, xDone + doneCol / 2, y + rowHeight / 2);
      ctx.font = "bold " + font;
      ctx.fillText(r.average, xAvg + avgCol / 2, y + rowHeight / 2);
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let ri = 0; ri <= data.rows.length; ri++) {
      const y = top + headerHeight + ri * rowHeight;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + tableWidth, y);
      ctx.stroke();
    }
    ctx.fillStyle = "#666";
    ctx.font = "12px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(RULE_NOTE(data), padding, top + headerHeight + rowHeight * data.rows.length + 16);
    if (hasTie) ctx.fillText(TIE_FOOTNOTE, padding, top + headerHeight + rowHeight * data.rows.length + 34);

    downloadCanvas(canvas, tournament.title, "_команды");
  }

  if (!data) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  return (
    <div style={{ ...panelStyle, marginTop: 20, border: "1px solid #b59f3b" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Командный зачёт</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {data.rows.length > 0 && (
            <>
              <CopyButton getText={handleCopy} />
              <button onClick={handleDownload} style={ghostButtonStyle}>Скачать таблицу</button>
              <CopyButton getText={handleCopyDetailed} label="Скопировать подробно" />
              <button onClick={handleDownloadDetailed} style={ghostButtonStyle}>Скачать подробную</button>
              {data.rows.some((r) => r.place.includes("-") || r.tie_resolved) && (
                <button onClick={tie.openTies} style={ghostButtonStyle}>Разобрать ничьи</button>
              )}
            </>
          )}
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      <p style={{ fontSize: 12, opacity: 0.65, marginTop: 6 }}>
        Место — по среднему числу попыток на слово: (попытки по пройденным словам, неугаданное = {data.unsolved_attempts}, + {data.skipped_attempts} за каждое
        непройденное) ÷ (участники × слова). Меньше — лучше. Нажмите на команду, чтобы увидеть игроков.
      </p>
      {tbMessage && (
        <div style={{ fontSize: 12, background: "#242426", borderRadius: 6, padding: "6px 10px", marginBottom: 8 }}>{tbMessage}</div>
      )}
      {tie.open && <TieResolutionPanel tie={tie} />}
      {data.rows.length === 0 ? (
        <div style={{ opacity: 0.7, fontSize: 13 }}>Пока нет команд, подходящих для зачёта (нужно не меньше 2 участников).</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th style={thStyle}>Место</th>
                <th style={thStyle}>Команда</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Игроков</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Слов пройдено</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Среднее</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <Fragment key={r.team_id}>
                  <tr onClick={() => toggleExpanded(r.team_id)} style={{ borderTop: "1px solid #2a2a2c", cursor: "pointer" }}>
                    <td style={{ ...tdStyle, fontWeight: !r.place.includes("-") ? 700 : 400 }}>{placeLabel(r)}</td>
                    <td style={tdStyle}>{expanded.has(r.team_id) ? "▾" : "▸"} {r.name}</td>
                    <td style={{ ...tdStyle, textAlign: "center" }}>{r.members_count}</td>
                    <td style={{ ...tdStyle, textAlign: "center" }}>{r.words_done}/{r.words_total}</td>
                    <td style={{ ...tdStyle, textAlign: "center", fontWeight: 700 }}>{r.average}</td>
                  </tr>
                  {expanded.has(r.team_id) && (
                    <tr>
                      <td></td>
                      <td colSpan={4} style={{ ...tdStyle, fontSize: 12, opacity: 0.85 }}>
                        {sortedMembers(r).map((m) => (
                          <div key={m.entry_id}>
                            {m.callsign} — среднее {m.average} · {m.words_done}/{data.words_count} слов, {m.total_attempts} попыток
                            {" · "}{m.cells.map(marathonCellLabel).join(" ")}
                            {!m.active && " (отключён)"}
                          </div>
                        ))}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.excluded.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 12, opacity: 0.8 }}>
          Не в зачёте (меньше 2 участников):{" "}
          {data.excluded.map((t) => `${t.name} (${t.members_count})`).join(", ")}
        </div>
      )}
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}
