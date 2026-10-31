import { useState } from "react";
import { api, buttonStyle, ghostButtonStyle } from "../adminShared.jsx";

// Разбор ничьих по итогам тай-брейка (см. пункт бэклога): окончательный порядок
// внутри групп с общим местом — место со звёздочкой, как "2*". Общий для
// стандартного режима и марафона (бэкенд: /tie-groups и /tie-resolutions).
// opts — для командного зачёта: другие адреса и поля (по умолчанию — игроки)
export function useTieResolution(tournamentId, onSaved, opts = {}) {
  const {
    groupsPath = "tie-groups", savePath = "tie-resolutions", idKey = "entry_id", idsKey = "entry_ids", nameKey = "callsign",
    renderGroupExtra = null,
  } = opts;
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null); // ответ /tie-groups | null
  const [state, setState] = useState({}); // place группы -> { use, order, source }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function initState(data) {
    const next = {};
    for (const g of data.groups) {
      const order = g.applied_order || g.suggested_order || g.members.map((m) => m[idKey]);
      next[g.place] = {
        use: Boolean(g.applied_order || g.suggested_order),
        order,
        source: g.applied_source || g.suggested_source || "вручную",
      };
    }
    setState(next);
  }

  async function openTies() {
    setOpen(true);
    setError("");
    try {
      const data = await api(`/api/admin/tournaments/${tournamentId}/${groupsPath}`);
      setData(data);
      initState(data);
    } catch (e) {
      setError(e.message);
    }
  }

  function moveTie(place, index, delta) {
    setState((prev) => {
      const st = prev[place];
      const order = [...st.order];
      const target = index + delta;
      if (target < 0 || target >= order.length) return prev;
      [order[index], order[target]] = [order[target], order[index]];
      return { ...prev, [place]: { ...st, order, use: true, source: "вручную" } };
    });
  }

  async function saveTies(resolutions) {
    setBusy(true);
    setError("");
    try {
      const data = await api(`/api/admin/tournaments/${tournamentId}/${savePath}`, {
        method: "PUT",
        body: JSON.stringify({ resolutions }),
      });
      setData(data);
      initState(data);
      if (onSaved) await onSaved();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function applySelected() {
    const resolutions = data.groups
      .filter((g) => state[g.place]?.use)
      .map((g) => ({ [idsKey]: state[g.place].order, source: state[g.place].source }));
    saveTies(resolutions);
  }

  return { open, setOpen, data, state, setState, busy, error, openTies, moveTie, saveTies, applySelected, idKey, nameKey, renderGroupExtra };
}

export function TieResolutionPanel({ tie }) {
  return (
        <div style={{ background: "#242426", borderRadius: 6, padding: 10, marginBottom: 12, maxWidth: 560 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <strong style={{ fontSize: 14 }}>{tie.idKey === "team_id" ? "Окончательные места при равном среднем" : "Окончательные места по итогам тай-брейка"}</strong>
            <button onClick={() => tie.setOpen(false)} style={{ ...ghostButtonStyle, fontSize: 11, padding: "1px 8px" }}>Закрыть</button>
          </div>
          {tie.error && <div style={{ color: "#e5484d", fontSize: 12, marginTop: 6 }}>{tie.error}</div>}
          {!tie.data ? (
            !tie.error && <p style={{ fontSize: 12, opacity: 0.7 }}>Загрузка...</p>
          ) : !tie.data.can_resolve ? (
            <p style={{ fontSize: 12, opacity: 0.8 }}>{tie.data.reason}</p>
          ) : tie.data.groups.length === 0 ? (
            <p style={{ fontSize: 12, opacity: 0.8 }}>Разделённых мест нет.</p>
          ) : (
            <>
              <p style={{ fontSize: 12, opacity: 0.7, margin: "6px 0" }}>
                {tie.idKey === "team_id"
                  ? "Порядок команд с равным средним задаётся вручную стрелками. Места, определённые разбором, помечаются звёздочкой (например, 2*)."
                  : "Порядок предложен по найденному тай-брейку, его можно поправить стрелками. Места, определённые тай-брейком, помечаются звёздочкой (например, 2*)."}
              </p>
              {tie.data.groups.map((g) => {
                const st = tie.state[g.place];
                if (!st) return null;
                const startPlace = parseInt(g.place.split("-")[0], 10);
                const nameOf = (id) => g.members.find((m) => m[tie.idKey] === id)?.[tie.nameKey] || id;
                return (
                  <div key={g.place} style={{ borderTop: "1px solid #3a3a3c", paddingTop: 8, marginTop: 8 }}>
                    <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                      <input
                        type="checkbox" checked={st.use}
                        onChange={(e) => tie.setState((prev) => ({ ...prev, [g.place]: { ...prev[g.place], use: e.target.checked } }))}
                      />
                      <span>Места {g.place} · {g.summary || `${g.points} очк.`}</span>
                      {g.applied_order && <span style={{ color: "#538d4e", fontSize: 12 }}>✓ применено</span>}
                    </label>
                    <div style={{ fontSize: 11, opacity: 0.7, margin: "2px 0 4px 22px" }}>
                      {st.source === "вручную"
                        ? "Порядок задан вручную"
                        : `По тай-брейку «${st.source}»`}
                      {!g.suggested_order && !g.applied_order && g.suggestion_note ? `. ${g.suggestion_note}` : ""}
                    </div>
                    {tie.renderGroupExtra && <div style={{ margin: "4px 0 6px 22px" }}>{tie.renderGroupExtra(g)}</div>}
                    <div style={{ marginLeft: 22 }}>
                      {st.order.map((id, i) => (
                        <div key={id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, padding: "2px 0" }}>
                          <span style={{ width: 28, fontWeight: 700 }}>{startPlace + i}*</span>
                          <span style={{ flex: 1, wordBreak: "break-word" }}>{nameOf(id)}</span>
                          <button
                            onClick={() => tie.moveTie(g.place, i, -1)} disabled={i === 0}
                            style={{ ...ghostButtonStyle, padding: "0 6px", fontSize: 12, opacity: i === 0 ? 0.3 : 1 }}
                          >↑</button>
                          <button
                            onClick={() => tie.moveTie(g.place, i, 1)} disabled={i === st.order.length - 1}
                            style={{ ...ghostButtonStyle, padding: "0 6px", fontSize: 12, opacity: i === st.order.length - 1 ? 0.3 : 1 }}
                          >↓</button>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <button onClick={tie.applySelected} disabled={tie.busy} style={{ ...buttonStyle, fontSize: 12, opacity: tie.busy ? 0.6 : 1 }}>
                  {tie.busy ? "Сохраняю..." : "Применить отмеченные"}
                </button>
                <button onClick={() => tie.saveTies([])} disabled={tie.busy} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                  Сбросить всё
                </button>
              </div>
            </>
          )}
        </div>
  );
}
