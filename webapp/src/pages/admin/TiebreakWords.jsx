import { useEffect, useState } from "react";
import { api, ghostButtonStyle, panelStyle, tdStyle, thStyle, useLatest } from "../adminShared.jsx";
import WordActions from "../WordActions.jsx";

export function TiebreakWordsPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [queue, setQueue] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/tiebreak-words`);
      if (tournamentIdRef.current === id) setQueue(data);
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  async function handleReroll(dayNumber) {
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/tiebreak-words/${dayNumber}/reroll`, { method: "POST" });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleLength(slot, length) {
    if (length == null || length === slot.length) return;
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/tiebreak-words/${slot.day_number}/length`, {
        method: "POST", body: JSON.stringify({ length }),
      });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleSetWord(dayNumber, text) {
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/tiebreak-words/${dayNumber}`, {
        method: "POST",
        body: JSON.stringify({ word: text }),
      });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  if (!queue) return null;

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Первые слова тай-брейка</h3>
        <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
      </div>
      <p style={{ fontSize: 13, opacity: 0.7 }}>
        Слово раунда 1 действует сразу после старта, остальные пригодятся только
        если часть участников сравняется по попыткам и понадобится продолжение.
        Уже наступивший раунд менять нельзя.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {queue.map((slot) => (
          <div key={slot.day_number} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ width: 70, opacity: 0.7, fontSize: 13 }}>Раунд {slot.day_number}</span>
            <span style={{ fontSize: 16, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, width: 110 }}>{slot.word}</span>
            {slot.editable ? (
              <WordActions
                compact word={slot.word} length={slot.length} onLength={(n) => handleLength(slot, n)}
                onReroll={() => handleReroll(slot.day_number)} onReplace={(text) => handleSetWord(slot.day_number, text)}
              />
            ) : (
              <span style={{ fontSize: 12, opacity: 0.5 }}>уже наступил</span>
            )}
          </div>
        ))}
      </div>
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}

// Слова командного тай-брейка: у каждого игрока в раунде своё слово (api/tiebreak.py).
export function TiebreakTeamWordsPanel({ tournament, refreshKey }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [days, setDays] = useState(null);
  const [openDay, setOpenDay] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/tiebreak-team-words`);
      if (tournamentIdRef.current === id) {
        setDays(data);
        setError("");
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    setDays(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id, tournament.teams_enabled, refreshKey]);

  async function call(path, body) {
    const id = tournament.id;
    setError("");
    setBusy(true);
    try {
      const res = await api(`/api/admin/tournaments/${id}/tiebreak-team-words/${path}`, {
        method: "POST", body: body ? JSON.stringify(body) : undefined,
      });
      if (tournamentIdRef.current === id) setDays(res);
    } catch (e) {
      setError(e.message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  if (!days) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Слова командного тай-брейка</h3>
        <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
      </div>
      <p style={{ fontSize: 13, opacity: 0.7 }}>
        У каждого игрока в раунде своё слово. Раунд 1 действует сразу после старта, остальные пригодятся, если команды
        сравняются по среднему (продолжение — только для равных команд). Слова наступившего раунда менять нельзя.
        «Одно слово на слот» даёт k-м игрокам всех команд слово первой команды — так все команды решают один набор слов.
      </p>
      {days.map((day) => {
        const maxSlot = Math.max(0, ...day.players.map((pl) => pl.slot));
        const isOpen = openDay === day.day_number;
        return (
          <div key={day.day_number} style={{ borderTop: "1px solid #2a2a2c", paddingTop: 6, marginTop: 6 }}>
            <button
              onClick={() => setOpenDay(isOpen ? null : day.day_number)}
              style={{ ...ghostButtonStyle, fontSize: 13 }}
            >
              {isOpen ? "▾" : "▸"} Раунд {day.day_number}
              {!day.editable && <span style={{ opacity: 0.6, fontWeight: 400 }}> · уже наступил</span>}
            </button>
            {isOpen && (
              day.players.length === 0 ? (
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
                  Пока некому играть: нужно хотя бы две команды, в каждой не меньше 2 подключённых игроков.
                </div>
              ) : (
                <>
                  {day.editable && maxSlot > 0 && (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "6px 0" }}>
                      {Array.from({ length: maxSlot }, (_, i) => (
                        <button
                          key={i} disabled={busy} onClick={() => call(`${day.day_number}/slot/${i + 1}/sync`)}
                          title={`Игроки №${i + 1} всех команд получат слово игрока №${i + 1} первой команды`}
                          style={{ ...ghostButtonStyle, fontSize: 11, padding: "2px 8px" }}
                        >
                          Одно слово на слот {i + 1}
                        </button>
                      ))}
                    </div>
                  )}
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
                      <thead>
                        <tr style={{ textAlign: "left", opacity: 0.7 }}>
                          <th style={thStyle}>Команда</th>
                          <th style={thStyle}>№</th>
                          <th style={thStyle}>Игрок</th>
                          <th style={thStyle}>Слово</th>
                          <th style={thStyle}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {day.players.map((pl) => {
                          return (
                            <tr key={pl.entry_id} style={{ borderTop: "1px solid #2a2a2c" }}>
                              <td style={tdStyle}>{pl.team_name}</td>
                              <td style={tdStyle}>{pl.slot}</td>
                              <td style={tdStyle}>{pl.callsign}</td>
                              <td style={{ ...tdStyle, textTransform: "uppercase", letterSpacing: 1, fontWeight: 700 }}>{pl.word}</td>
                              <td style={tdStyle}>
                                {pl.editable && (
                                  <WordActions
                                    compact word={pl.word} length={pl.length} disabled={busy}
                                    onLength={(n) => call(`${day.day_number}/${pl.entry_id}/length`, { length: n })}
                                    onReroll={() => call(`${day.day_number}/${pl.entry_id}/reroll`)}
                                    onReplace={(text) => call(`${day.day_number}/${pl.entry_id}`, { word: text })}
                                  />
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )
            )}
          </div>
        );
      })}
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}
