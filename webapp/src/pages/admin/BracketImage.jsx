import { useRef, useState } from "react";
import { ghostButtonStyle } from "../adminShared.jsx";
import { formatMatchResults } from "./bracketFormat.jsx";

const BOX_W = 240;

const MAX_CALLSIGN_CHARS = 15;

// Длинный позывной не должен налезать на результаты и вылезать из ячейки.
function shortCallsign(name) {
  const chars = Array.from(name);
  return chars.length > MAX_CALLSIGN_CHARS ? chars.slice(0, MAX_CALLSIGN_CHARS).join("") + "..." : name;
}

const BOX_H = 44;

const GAP_Y = 18;

const COL_GAP = 70;

const PAD = 24;

export function roundLabel(matchesInRound) {
  if (matchesInRound === 1) return "Финал";
  if (matchesInRound === 2) return "1/2 финала";
  return `1/${matchesInRound} финала`;
}

function svgToPngBlob(svgEl, width, height) {
  return new Promise((resolve, reject) => {
    const svgStr = new XMLSerializer().serializeToString(svgEl);
    const svgBlob = new Blob([svgStr], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    const img = new Image();
    img.onload = () => {
      const scale = 2;
      const canvas = document.createElement("canvas");
      canvas.width = width * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#121213";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.scale(scale, scale);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Не удалось создать изображение"))), "image/png");
    };
    img.onerror = () => reject(new Error("Не удалось отрисовать сетку"));
    img.src = url;
  });
}

export function BracketImage({ tournament, matches }) {
  const svgRef = useRef(null);
  const [status, setStatus] = useState("");

  const totalRounds = Math.round(Math.log2(tournament.bracket_size));
  const matchByKey = new Map(matches.map((m) => [`${m.round_number}:${m.position}`, m]));

  function feederWinnerName(feeder) {
    if (!feeder || feeder.winner_entry_id == null) return null;
    return feeder.winner_entry_id === feeder.entry_a_id ? feeder.entry_a_callsign : feeder.entry_b_callsign;
  }

  // Победитель пары проходит дальше по сетке сразу, не дожидаясь, пока решится
  // соседняя пара (реальная запись следующего раунда появляется в БД только
  // когда решены ОБЕ пары половины) — здесь для отображения строим "виртуальную"
  // пару из уже известных победителей, пока настоящей записи ещё нет.
  const rounds = [];
  for (let r = 1; r <= totalRounds; r++) {
    const count = tournament.bracket_size / 2 ** r;
    const slots = [];
    for (let p = 0; p < count; p++) {
      const real = matchByKey.get(`${r}:${p}`);
      if (real) {
        slots.push(real);
        continue;
      }
      if (r === 1) {
        slots.push(null);
        continue;
      }
      const prevRound = rounds[r - 2];
      const nameA = feederWinnerName(prevRound[2 * p]);
      const nameB = feederWinnerName(prevRound[2 * p + 1]);
      slots.push(
        nameA || nameB
          ? {
              entry_a_callsign: nameA, entry_b_callsign: nameB,
              entry_a_id: null, entry_b_id: null, winner_entry_id: null,
              entry_a_attempts_used: null, entry_a_solved: null,
              entry_b_attempts_used: null, entry_b_solved: null,
            }
          : null
      );
    }
    rounds.push(slots);
  }

  const centers = [rounds[0].map((_, i) => PAD + i * (BOX_H + GAP_Y) + BOX_H / 2)];
  for (let r = 1; r < rounds.length; r++) {
    centers.push(rounds[r].map((_, i) => (centers[r - 1][2 * i] + centers[r - 1][2 * i + 1]) / 2));
  }

  // Игра за 3 место — отдельный блок под финалом (светло-серый, как чётные пары).
  const showThird = !!tournament.third_place_match && totalRounds >= 2;
  const thirdMatch = matches.find((m) => m.is_third_place);
  const finalCenter = centers[centers.length - 1][0];
  const thirdY = finalCenter + BOX_H / 2 + 56;
  const svgHeight = Math.max(
    Math.max(...centers[0]) + BOX_H / 2 + PAD,
    showThird ? thirdY + BOX_H + PAD : 0
  );
  const svgWidth = totalRounds * (BOX_W + COL_GAP) + PAD;

  function renderBox(key, m, x, y, gray) {
    const nameA = m?.entry_a_callsign || "?";
    const nameB = m?.entry_b_callsign || "?";
    const winnerA = m?.winner_entry_id != null && m.winner_entry_id === m.entry_a_id;
    const winnerB = m?.winner_entry_id != null && m.winner_entry_id === m.entry_b_id;
    const attemptsA = formatMatchResults(m, "a");
    const attemptsB = formatMatchResults(m, "b");
    return (
      <g key={key}>
        <rect x={x} y={y} width={BOX_W} height={BOX_H} rx={6} fill={gray ? "#fafafa" : "#ffffff"} stroke="#ddd" />
        <line x1={x} y1={y + BOX_H / 2} x2={x + BOX_W} y2={y + BOX_H / 2} stroke="#ddd" />
        <text x={x + 8} y={y + BOX_H / 2 - 6} fontSize="13" fill={winnerA ? "#6aaa64" : "#1a1a1b"} fontWeight={winnerA ? "700" : "400"}>
          {shortCallsign(nameA)}
        </text>
        <text x={x + BOX_W - 8} y={y + BOX_H / 2 - 6} fontSize="11" textAnchor="end" fill={winnerA ? "#6aaa64" : "#999"}>
          {attemptsA}
        </text>
        <text x={x + 8} y={y + BOX_H - 6} fontSize="13" fill={winnerB ? "#6aaa64" : "#1a1a1b"} fontWeight={winnerB ? "700" : "400"}>
          {shortCallsign(nameB)}
        </text>
        <text x={x + BOX_W - 8} y={y + BOX_H - 6} fontSize="11" textAnchor="end" fill={winnerB ? "#6aaa64" : "#999"}>
          {attemptsB}
        </text>
      </g>
    );
  }

  async function handleDownload() {
    setStatus("");
    try {
      const blob = await svgToPngBlob(svgRef.current, svgWidth, svgHeight);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `bracket-${tournament.id}.png`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatus(`Не удалось скачать: ${e.message}`);
    }
  }

  async function handleCopy() {
    setStatus("");
    try {
      const blob = await svgToPngBlob(svgRef.current, svgWidth, svgHeight);
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      setStatus("Скопировано — можно вставить в чат.");
    } catch (e) {
      setStatus("Браузер не поддерживает копирование картинки — воспользуйтесь скачиванием.");
    }
    setTimeout(() => setStatus(""), 4000);
  }

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <button onClick={handleCopy} style={ghostButtonStyle}>Скопировать картинку</button>
        <button onClick={handleDownload} style={ghostButtonStyle}>Скачать PNG</button>
        {status && <span style={{ fontSize: 12, opacity: 0.7 }}>{status}</span>}
      </div>
      <div style={{ overflowX: "auto", background: "#ffffff", borderRadius: 8, padding: 8 }}>
        <svg ref={svgRef} width={svgWidth} height={svgHeight} viewBox={`0 0 ${svgWidth} ${svgHeight}`} fontFamily="system-ui, sans-serif">
          <rect x={0} y={0} width={svgWidth} height={svgHeight} fill="#ffffff" />
          {rounds.map((slots, rIdx) => {
            const x = PAD + rIdx * (BOX_W + COL_GAP);
            return (
              <g key={`round-${rIdx}`}>
                <text x={x + BOX_W / 2} y={PAD - 8} textAnchor="middle" fontSize="12" fontWeight="bold" fill="#666">
                  {roundLabel(slots.length)}
                </text>
                {slots.map((m, i) => renderBox(`box-${rIdx}-${i}`, m, x, centers[rIdx][i] - BOX_H / 2, i % 2 === 1))}
              </g>
            );
          })}
          {showThird && (
            <g key="third-place">
              <text
                x={PAD + (totalRounds - 1) * (BOX_W + COL_GAP) + BOX_W / 2} y={thirdY - 10}
                textAnchor="middle" fontSize="12" fontWeight="bold" fill="#666"
              >
                Игра за 3 место
              </text>
              {renderBox("box-third", thirdMatch, PAD + (totalRounds - 1) * (BOX_W + COL_GAP), thirdY, true)}
            </g>
          )}
          {rounds.slice(0, -1).map((_, r) => {
            const x1 = PAD + r * (BOX_W + COL_GAP) + BOX_W;
            const xMid = x1 + COL_GAP / 2;
            const x2 = PAD + (r + 1) * (BOX_W + COL_GAP);
            return centers[r + 1].map((cy, i) => {
              const yA = centers[r][2 * i];
              const yB = centers[r][2 * i + 1];
              return (
                <path
                  key={`line-${r}-${i}`}
                  d={`M ${x1} ${yA} H ${xMid} V ${yB} M ${xMid} ${cy} H ${x2}`}
                  fill="none"
                  stroke="#ddd"
                />
              );
            });
          })}
        </svg>
      </div>
    </div>
  );
}
