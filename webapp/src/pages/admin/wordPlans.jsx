import { useEffect, useState } from "react";
import { LengthSelect, api, buttonStyle, ghostButtonStyle, inputStyle, tdStyle, thStyle } from "../adminShared.jsx";

// Сохраняет один раздел плана длин (marathon / playoff / tiebreak), не трогая остальные.
export function saveWordPlanPart(tournament, key, value) {
  const plan = { ...(tournament.word_plan || {}) };
  if (value == null) delete plan[key];
  else plan[key] = value;
  return api(`/api/admin/tournaments/${tournament.id}/word-plan`, { method: "PUT", body: JSON.stringify({ plan }) });
}

// Таблица «строка × номер слота» с выбором длины в каждой клетке. Пустая клетка — базовая длина
// розыгрыша. plan: { ключ_строки: [длины...] }; onSave получает такой же объект (или null, если
// везде пусто). Ключи плана, которых нет среди строк, сохраняются как были.
// Число обязательных игр в паре по стадиям (1-5). Остальные игры пары — дополнительные, при ничьей.
// Сохраняется в плане слов (word_plan.playoff_games); ещё не начатые пары подстраиваются сразу.
export function PlayoffGamesPlan({ tournament, rows, onSaved }) {
  const stored = tournament.word_plan?.playoff_games || {};
  const planKey = JSON.stringify(stored) + "|" + rows.map((r) => r.key).join(",");
  const [open, setOpen] = useState(false);
  const [counts, setCounts] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const next = {};
    rows.forEach((r) => { next[r.key] = stored[r.key] || 1; });
    setCounts(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planKey]);

  async function handleSave() {
    setBusy(true);
    setError("");
    try {
      const shown = new Set(rows.map((r) => r.key));
      const value = {};
      Object.entries(stored).forEach(([k, n]) => { if (!shown.has(k)) value[k] = n; });
      rows.forEach((r) => { if (counts[r.key] > 1) value[r.key] = counts[r.key]; });
      await saveWordPlanPart(tournament, "playoff_games", Object.keys(value).length ? value : null);
      if (onSaved) await onSaved();
      setSaved(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const summary = rows.map((r) => counts[r.key] || 1);
  return (
    <div style={{ marginBottom: 12 }}>
      <button onClick={() => setOpen((v) => !v)} style={{ ...ghostButtonStyle, fontSize: 13 }}>
        {open ? "▾" : "▸"} Число игр в паре по стадиям{!open && summary.some((n) => n > 1) ? ` (${summary.join(" / ")})` : ""}
      </button>
      {open && (
        <div style={{ marginTop: 8, padding: 10, border: "1px solid #3a3a3c", borderRadius: 6 }}>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>
            Сколько обязательных игр играют в паре, все подряд в день раунда. Побеждает тот, у кого меньше сумма попыток
            (неугаданное слово — 7); при равной сумме проигрывает тот, у кого больше неугаданных слов. Пропуск хотя бы
            одной обязательной игры — поражение в паре. Если равенство сохраняется — одна дополнительная игра решает
            пару (повторяется до победителя). Ещё не начатые пары подстраиваются сразу, начатые не меняются.
          </div>
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>{r.label}</td>
                  <td style={tdStyle}>
                    <select
                      value={counts[r.key] || 1}
                      onChange={(e) => { setSaved(false); setCounts((prev) => ({ ...prev, [r.key]: Number(e.target.value) })); }}
                      style={{ ...inputStyle, padding: "2px 6px", fontSize: 13 }}
                    >
                      {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n === 1 ? "1 игра" : n < 5 ? `${n} игры` : `${n} игр`}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <button onClick={handleSave} disabled={busy} style={{ ...buttonStyle, padding: "4px 12px", fontSize: 12 }}>Сохранить</button>
            {saved && <span style={{ fontSize: 12, color: "#538d4e" }}>Сохранено</span>}
            {error && <span style={{ fontSize: 12, color: "#e5484d" }}>{error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export function LengthPlanGrid({ title, hint, colLabel, rows, slots, plan, base, onSave }) {
  const toCells = (list) => Array.from({ length: slots }, (_, i) => (list && list.length ? list[Math.min(i, list.length - 1)] : null));
  const planKey = JSON.stringify(plan || {}) + "|" + rows.map((r) => r.key).join(",");
  const [open, setOpen] = useState(false);
  const [cells, setCells] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const next = {};
    rows.forEach((r) => { next[r.key] = toCells(plan?.[r.key]); });
    setCells(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planKey]);

  function setCell(key, i, value) {
    setSaved(false);
    setCells((prev) => ({ ...prev, [key]: prev[key].map((c, j) => (j === i ? value : c)) }));
  }

  async function handleSave() {
    setBusy(true);
    setError("");
    try {
      const shown = new Set(rows.map((r) => r.key));
      const value = {};
      Object.entries(plan || {}).forEach(([k, list]) => { if (!shown.has(k)) value[k] = list; });
      rows.forEach((r) => {
        const row = cells[r.key] || [];
        if (row.some((c) => c != null)) value[r.key] = row.map((c) => c ?? base);
      });
      await onSave(Object.keys(value).length ? value : null);
      setSaved(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <button onClick={() => setOpen((v) => !v)} style={{ ...ghostButtonStyle, fontSize: 13 }}>
        {open ? "▾" : "▸"} {title}
      </button>
      {open && (
        <div style={{ marginTop: 8, padding: 10, border: "1px solid #3a3a3c", borderRadius: 6 }}>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>{hint}</div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", opacity: 0.7 }}>
                  <th style={thStyle}></th>
                  {Array.from({ length: slots }, (_, i) => <th key={i} style={thStyle}>{colLabel} {i + 1}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key} style={{ borderTop: "1px solid #2a2a2c" }}>
                    <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>{r.label}</td>
                    {(cells[r.key] || []).map((c, i) => (
                      <td key={i} style={tdStyle}>
                        <LengthSelect value={c} allowEmpty emptyLabel={`как базовая (${base})`} onChange={(n) => setCell(r.key, i, n)} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <button onClick={handleSave} disabled={busy} style={{ ...buttonStyle, padding: "4px 12px", fontSize: 12 }}>Сохранить</button>
            {saved && <span style={{ fontSize: 12, color: "#538d4e" }}>Сохранено</span>}
            {error && <span style={{ fontSize: 12, color: "#e5484d" }}>{error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
