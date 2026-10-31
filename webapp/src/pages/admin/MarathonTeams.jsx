import { useEffect, useState } from "react";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, tdStyle, thStyle, useLatest } from "../adminShared.jsx";
import { askConfirm } from "../confirmDialog.jsx";

// Команды марафона: создание/переименование/удаление и распределение игроков (api/teams.py).
export function MarathonTeamsPanel({ tournament, onChanged, refreshKey }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [teams, setTeams] = useState(null);
  const [entries, setEntries] = useState([]);
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editName, setEditName] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const [t, e] = await Promise.all([
        api(`/api/admin/tournaments/${id}/teams`),
        api(`/api/admin/tournaments/${id}/entries`),
      ]);
      if (tournamentIdRef.current === id) {
        setTeams(t);
        setEntries(e);
      }
    } catch (err) {
      if (tournamentIdRef.current === id) setError(err.message);
    }
  }

  useEffect(() => {
    setTeams(null);
    setEditingId(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id, refreshKey]);

  async function run(action) {
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e.message);
    }
    await refresh();
    if (onChanged) onChanged();
  }

  function handleCreate(ev) {
    ev.preventDefault();
    if (!newName.trim()) return;
    run(async () => {
      await api(`/api/admin/tournaments/${tournament.id}/teams`, { method: "POST", body: JSON.stringify({ name: newName }) });
      setNewName("");
    });
  }

  function handleRename(team) {
    run(async () => {
      await api(`/api/admin/teams/${team.id}`, { method: "PATCH", body: JSON.stringify({ name: editName }) });
      setEditingId(null);
    });
  }

  async function handleDelete(team) {
    if (!await askConfirm(`Удалить команду «${team.name}»? Её участники останутся в розыгрыше без команды.`)) return;
    run(() => api(`/api/admin/teams/${team.id}`, { method: "DELETE" }));
  }

  function handleAssign(entry, value) {
    run(() => api(`/api/admin/entries/${entry.id}/team`, {
      method: "PUT", body: JSON.stringify({ team_id: value === "" ? null : Number(value) }),
    }));
  }

  if (!teams) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  const teamName = (id) => teams.find((t) => t.id === id)?.name || "";
  const counted = (team) => entries.filter((e) => e.team_id === team.id && !e.hidden_from_standings);
  const q = search.trim().toLowerCase();
  const shown = entries
    .filter((e) => !q || e.callsign.toLowerCase().includes(q) || teamName(e.team_id).toLowerCase().includes(q))
    .sort((a, b) => {
      const ta = a.team_id == null ? "\uffff" : teamName(a.team_id).toLowerCase();
      const tb = b.team_id == null ? "\uffff" : teamName(b.team_id).toLowerCase();
      return ta !== tb ? ta.localeCompare(tb, "ru") : a.callsign.localeCompare(b.callsign, "ru");
    });

  return (
    <div style={{ ...panelStyle, marginTop: 20, border: "1px solid #b59f3b" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Команды «{tournament.title}»</h3>
        <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
      </div>
      {tournament.type === "tiebreak" ? (
        <p style={{ fontSize: 13, opacity: 0.7 }}>
          В раунд попадают игроки команд, где не меньше 2 подключённых игроков (нужно хотя бы две такие команды).
          Игроки без команды не играют. Состав нужно собрать до начала тай-брейка — после старта менять нельзя.
        </p>
      ) : (
        <p style={{ fontSize: 13, opacity: 0.7 }}>
          Команда идёт в зачёт, если в ней не меньше 2 участников (скрытые из таблицы не считаются). Состав можно менять
          в любой момент — таблица пересчитывается сразу. Игрок без команды остаётся только в личном зачёте.
        </p>
      )}
      {tournament.type !== "tiebreak" && !tournament.individual_words && (
        <p style={{ fontSize: 12, color: "#e5a94c" }}>
          Внимание: у всех общий набор слов — участники одной команды могут подсказывать друг другу ответы.
        </p>
      )}
      <form onSubmit={handleCreate} style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input
          placeholder="Название новой команды" value={newName} maxLength={100}
          onChange={(e) => setNewName(e.target.value)} style={{ ...inputStyle, flex: "1 1 200px" }}
        />
        <button type="submit" disabled={!newName.trim()} style={buttonStyle}>Создать команду</button>
      </form>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

      {teams.length === 0 ? (
        <div style={{ opacity: 0.7, fontSize: 13 }}>Команд пока нет.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
          {teams.map((team) => {
            const members = entries.filter((e) => e.team_id === team.id);
            const small = counted(team).length < 2;
            return (
              <div key={team.id} style={{ background: "#242426", borderRadius: 6, padding: "6px 10px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  {editingId === team.id ? (
                    <>
                      <input
                        autoFocus value={editName} maxLength={100} onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") handleRename(team); if (e.key === "Escape") setEditingId(null); }}
                        style={{ ...inputStyle, padding: "2px 6px", fontSize: 13, width: 180 }}
                      />
                      <button onClick={() => handleRename(team)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
                      <button onClick={() => setEditingId(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
                    </>
                  ) : (
                    <>
                      <strong style={{ fontSize: 14 }}>{team.name}</strong>
                      <button
                        onClick={() => { setEditingId(team.id); setEditName(team.name); }}
                        title="Переименовать" style={{ ...ghostButtonStyle, padding: "0 6px", fontSize: 11 }}
                      >✎</button>
                      <span style={{ fontSize: 12, opacity: 0.7 }}>{counted(team).length} в зачёте</span>
                      {small && <span style={{ fontSize: 12, color: "#e5a94c" }}>меньше 2 участников — в зачёт не идёт</span>}
                      <button
                        onClick={() => handleDelete(team)} title="Удалить команду"
                        style={{ ...ghostButtonStyle, padding: "0 6px", fontSize: 11, marginLeft: "auto" }}
                      >✕</button>
                    </>
                  )}
                </div>
                <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
                  {members.length === 0 ? "нет участников" : members.map((e) => e.callsign + (e.hidden_from_standings ? " (не в таблице)" : "")).join(", ")}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <input
        placeholder="🔎 Поиск по позывному или команде" value={search} onChange={(e) => setSearch(e.target.value)}
        style={{ ...inputStyle, marginBottom: 8, maxWidth: 300 }}
      />
      <div style={{ maxHeight: 340, overflowY: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left", opacity: 0.7 }}>
              <th style={thStyle}>Позывной</th>
              <th style={thStyle}>Команда</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.id} style={{ borderTop: "1px solid #2a2a2c", opacity: e.active ? 1 : 0.5 }}>
                <td style={tdStyle}>
                  {e.callsign}
                  {!e.active && <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.7 }}>отключён</span>}
                </td>
                <td style={tdStyle}>
                  <select
                    value={e.team_id ?? ""} onChange={(ev) => handleAssign(e, ev.target.value)}
                    style={{ ...inputStyle, padding: "2px 4px", fontSize: 12, width: "auto", minWidth: 160 }}
                  >
                    <option value="">— без команды —</option>
                    {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && <div style={{ opacity: 0.6, fontSize: 13, marginTop: 6 }}>Никого не найдено.</div>}
      </div>
    </div>
  );
}
