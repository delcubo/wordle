import { Fragment, useEffect, useState } from "react";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, tdStyle, useLatest } from "../adminShared.jsx";
import WordActions from "../WordActions.jsx";
import { LengthPlanGrid, PlayoffGamesPlan, saveWordPlanPart } from "./wordPlans.jsx";
import { MATCH_STATUS_LABEL, formatMatchResults } from "./bracketFormat.jsx";
import { BracketImage, roundLabel } from "./BracketImage.jsx";

function MatchWordQueue({ matchId, gamesRequired = 1 }) {
  const matchIdRef = useLatest(matchId);
  const [queue, setQueue] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    const id = matchId;
    try {
      const data = await api(`/api/admin/bracket/matches/${id}/words`);
      if (matchIdRef.current === id) {
        setQueue(data);
        setError("");
      }
    } catch (e) {
      if (matchIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId]);

  async function handleSet(gameNumber, text) {
    setError("");
    try {
      await api(`/api/admin/bracket/matches/${matchId}/words/${gameNumber}`, {
        method: "POST",
        body: JSON.stringify({ word: text }),
      });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleLength(q, length) {
    if (length == null || length === q.length) return;
    setError("");
    try {
      await api(`/api/admin/bracket/matches/${matchId}/words/${q.game_number}/length`, {
        method: "POST", body: JSON.stringify({ length }),
      });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleReroll(gameNumber) {
    setError("");
    try {
      await api(`/api/admin/bracket/matches/${matchId}/words/${gameNumber}/reroll`, { method: "POST" });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  if (!queue) return null;

  return (
    <div style={{ padding: 8, background: "#232325", borderRadius: 6 }}>
      <div style={{ fontSize: 11, opacity: 0.6, marginBottom: 4 }}>
        {gamesRequired > 1
          ? `Очередь слов — игры 1-${gamesRequired}: обязательные (играются подряд), `
          : "Очередь слов — 1: текущее, "}
        {gamesRequired >= 5 ? "" : `${gamesRequired + 1}-5: превью на случай ничьей `}(каждое слово задаётся независимо). С 6-й игры слова генерируются автоматически.
      </div>
      {error && <div style={{ color: "#e5484d", fontSize: 11, marginBottom: 4 }}>{error}</div>}
      {queue.map((q) => (
        <div key={q.game_number} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
          <span style={{ fontSize: 11, opacity: 0.6, width: 55 }}>Игра {q.game_number}:</span>
          <span style={{ textTransform: "uppercase", letterSpacing: 1, fontSize: 13, minWidth: 70 }}>{q.word}</span>
          {q.editable && (
            <WordActions
              compact word={q.word} length={q.length} onLength={(n) => handleLength(q, n)}
              onReroll={() => handleReroll(q.game_number)} onReplace={(text) => handleSet(q.game_number, text)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export function BracketPanel({ tournament, onTournamentChanged }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [entries, setEntries] = useState([]);
  const [matches, setMatches] = useState(null);
  const [pairSelections, setPairSelections] = useState([]);
  const [error, setError] = useState("");
  const [overriding, setOverriding] = useState(null); // matchId | null
  const [overrideNote, setOverrideNote] = useState("");
  const [wordQueueOpenId, setWordQueueOpenId] = useState(null); // matchId | null

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/bracket`);
      if (tournamentIdRef.current === id) {
        setMatches(data);
        setError("");
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    const id = tournament.id;
    api(`/api/admin/tournaments/${id}/entries`).then((data) => {
      if (tournamentIdRef.current === id) setEntries(data);
    }).catch(() => {});
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id, tournament.third_place_match]);

  const pairsNeeded = tournament.bracket_size ? tournament.bracket_size / 2 : 0;

  useEffect(() => {
    setPairSelections(Array.from({ length: pairsNeeded }, () => ({ a: "", b: "" })));
  }, [pairsNeeded, tournament.id]);

  async function handleGenerate() {
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/bracket/generate`, { method: "POST" });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  function updatePair(index, side, value) {
    setPairSelections((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [side]: value };
      return next;
    });
  }

  async function handleSubmitRound1(e) {
    e.preventDefault();
    setError("");
    try {
      const pairs = pairSelections.map((p) => [p.a ? Number(p.a) : null, p.b ? Number(p.b) : null]);
      await api(`/api/admin/tournaments/${tournament.id}/bracket/round1`, {
        method: "POST",
        body: JSON.stringify({ pairs }),
      });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleOverride(matchId, winnerEntryId) {
    setError("");
    try {
      await api(`/api/admin/bracket/matches/${matchId}/override`, {
        method: "POST",
        body: JSON.stringify({ winner_entry_id: winnerEntryId, note: overrideNote }),
      });
      setOverriding(null);
      setOverrideNote("");
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  const bracketExists = matches && matches.length > 0;

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ marginTop: 0 }}>Сетка плей-офф</h3>
        <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
      </div>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

      {tournament.bracket_size >= 2 && (() => {
        const stages = Math.round(Math.log2(tournament.bracket_size));
        const rows = Array.from({ length: stages }, (_, i) => ({
          key: String(i + 1), label: roundLabel(tournament.bracket_size / 2 ** (i + 1)),
        }));
        if (tournament.third_place_match) rows.push({ key: "third", label: "Игра за 3 место" });
        return (
          <>
          <PlayoffGamesPlan
            tournament={tournament} rows={rows}
            onSaved={async () => { if (onTournamentChanged) await onTournamentChanged(); await refresh(); }}
          />
          <LengthPlanGrid
            title="Длины слов по стадиям" colLabel="Игра" slots={5} base={tournament.word_length || 5} rows={rows}
            hint="Длина слова для каждой игры пары на каждой стадии (игра 2+ нужна только при ничьей). Действует на ещё не созданные слова; уже заданные слова пар меняются в «очереди слов» пары."
            plan={tournament.word_plan?.playoff || null}
            onSave={async (value) => {
              await saveWordPlanPart(tournament, "playoff", value);
              if (onTournamentChanged) await onTournamentChanged();
            }}
          />
          </>
        );
      })()}

      {!bracketExists && tournament.type === "championship" && (
        <button onClick={handleGenerate} style={buttonStyle}>Сгенерировать сетку по итогам</button>
      )}

      {!bracketExists && tournament.type === "knockout" && (
        <form onSubmit={handleSubmitRound1} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <p style={{ opacity: 0.6, fontSize: 12, marginTop: -4 }}>
            «— пусто —» с обеих сторон — пара без игроков (если не набралось 2^N участников);
            с одной стороны — единственный игрок проходит дальше автоматически, без игры.
          </p>
          {pairSelections.map((p, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ opacity: 0.7, fontSize: 13 }}>Пара {i + 1}:</span>
              <select value={p.a} onChange={(e) => updatePair(i, "a", e.target.value)} style={inputStyle}>
                <option value="">— пусто —</option>
                {entries.map((en) => <option key={en.id} value={en.id}>{en.callsign}</option>)}
              </select>
              <select value={p.b} onChange={(e) => updatePair(i, "b", e.target.value)} style={inputStyle}>
                <option value="">— пусто —</option>
                {entries.map((en) => <option key={en.id} value={en.id}>{en.callsign}</option>)}
              </select>
            </div>
          ))}
          <button type="submit" style={buttonStyle}>Сохранить раунд 1</button>
        </form>
      )}

      {bracketExists && (
        <>
          <table style={{ borderCollapse: "collapse", fontSize: 13, marginTop: 8 }}>
            <tbody>
              {matches.map((m) => {
                const hasBothSides = m.entry_a_id != null && m.entry_b_id != null;
                const hasAnySide = m.entry_a_id != null || m.entry_b_id != null;
                return (
                <Fragment key={m.id}>
                <tr style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={tdStyle}>
                    {m.is_third_place ? "Игра за 3 место" : `Р${m.round_number} · пара ${m.position + 1}`}
                    {m.is_sudden_death && <span style={{ opacity: 0.6 }}> (доп. раунд)</span>}
                    {(m.games_required || 1) > 1 && (
                      <span style={{ opacity: 0.6 }}> · {m.games_required} {m.games_required < 5 ? "игры" : "игр"}</span>
                    )}
                    {(() => {
                      // слова ВСЕХ игр пары по порядку (после ничьей игр несколько)
                      const words = (m.games || []).map((g) => g.word).filter(Boolean);
                      const list = words.length ? words : m.word ? [m.word] : [];
                      if (!list.length) return null;
                      return (
                        <div style={{ opacity: 0.6, fontSize: 11, textTransform: "uppercase" }}>
                          {list.length > 1 ? "слова" : "слово"}: {list.join(" · ")}
                        </div>
                      );
                    })()}
                  </td>
                  <td style={tdStyle}>{m.entry_a_callsign || "— пусто —"} {formatMatchResults(m, "a", true)}</td>
                  <td style={tdStyle}>—</td>
                  <td style={tdStyle}>{m.entry_b_callsign || "— пусто —"} {formatMatchResults(m, "b", true)}</td>
                  <td style={{ ...tdStyle, opacity: 0.7 }}>
                    {m.winner_entry_id
                      ? <>победил: {m.winner_entry_id === m.entry_a_id ? m.entry_a_callsign : m.entry_b_callsign}
                        {m.admin_note && <sup title={`Скорректировано: ${m.admin_note}`} style={{ color: "#e5a94c" }}> ✎</sup>}</>
                      : (m.status === "finished"
                          ? (hasAnySide ? "не сыграли — никто не прошёл дальше" : "пустая пара")
                          : MATCH_STATUS_LABEL[m.status] || m.status)}
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {hasAnySide && m.status !== "finished" && (
                        <button
                          onClick={() => setWordQueueOpenId(wordQueueOpenId === m.id ? null : m.id)}
                          style={{ ...ghostButtonStyle, padding: "2px 6px", fontSize: 11 }}
                        >
                          Слова
                        </button>
                      )}
                      {!m.winner_entry_id && m.status !== "finished" && (
                        overriding === m.id ? (
                          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                            <input
                              placeholder="Причина" value={overrideNote}
                              onChange={(e) => setOverrideNote(e.target.value)}
                              style={{ ...inputStyle, padding: "2px 6px", fontSize: 12, width: 100 }}
                            />
                            <button
                              onClick={() => handleOverride(m.id, m.entry_a_id)}
                              disabled={!overrideNote.trim()}
                              style={{ ...ghostButtonStyle, padding: "2px 6px", fontSize: 11 }}
                            >
                              Победил {m.entry_a_callsign || "A"}
                            </button>
                            <button
                              onClick={() => handleOverride(m.id, m.entry_b_id)}
                              disabled={!overrideNote.trim()}
                              style={{ ...ghostButtonStyle, padding: "2px 6px", fontSize: 11 }}
                            >
                              Победил {m.entry_b_callsign || "B"}
                            </button>
                            <button onClick={() => { setOverriding(null); setOverrideNote(""); }} style={{ ...ghostButtonStyle, padding: "2px 6px", fontSize: 11 }}>×</button>
                          </div>
                        ) : (
                          <button onClick={() => setOverriding(m.id)} style={{ ...ghostButtonStyle, padding: "2px 6px", fontSize: 11 }}>
                            Назначить победителя
                          </button>
                        )
                      )}
                    </div>
                  </td>
                </tr>
                {wordQueueOpenId === m.id && (
                  <tr>
                    <td colSpan={6} style={{ padding: "0 8px 8px" }}>
                      <MatchWordQueue matchId={m.id} gamesRequired={m.games_required || 1} />
                    </td>
                  </tr>
                )}
                </Fragment>
                );
              })}
            </tbody>
          </table>
          <BracketImage tournament={tournament} matches={matches} />
        </>
      )}
    </div>
  );
}
