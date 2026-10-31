import { useEffect, useState } from "react";
import { LengthSelect, api, ghostButtonStyle, inputStyle, panelStyle, tdStyle, thStyle, useLatest } from "../adminShared.jsx";
import WordActions from "../WordActions.jsx";
import { askConfirm } from "../confirmDialog.jsx";
import { GuessesPopup } from "./GuessesPopup.jsx";

export function MarathonWordsPanel({ tournament, onTournamentChanged }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [words, setWords] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/marathon/words`);
      if (tournamentIdRef.current === id) {
        setWords(data);
        setError("");
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    setWords(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id, tournament.words_count]);

  async function handleLength(w, length) {
    if (length == null || length === w.length) return;
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/marathon/word-length?number=${w.day_number}`, {
        method: "POST", body: JSON.stringify({ length }),
      });
      if (onTournamentChanged) await onTournamentChanged();
      await refresh();
    } catch (e) {
      setError(e.message);
      await refresh();
    }
  }

  async function handleReroll(w) {
    setError("");
    try {
      await api(`/api/admin/words/${w.id}/reroll`, { method: "POST" });
      await refresh();
    } catch (e) {
      setError(e.message);
      await refresh();
    }
  }

  async function handleReplace(w, text) {
    setError("");
    try {
      await api(`/api/admin/words/${w.id}/confirm`, { method: "POST", body: JSON.stringify({ override_word: text }) });
      await refresh();
    } catch (e) {
      setError(e.message);
      await refresh();
    }
  }

  if (!words) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  return (
    <div style={{ ...panelStyle, marginTop: 20, border: "1px solid #b59f3b" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Слова марафона</h3>
        <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
      </div>
      <p style={{ fontSize: 13, opacity: 0.7 }}>
        Это ответы — не показывайте этот экран участникам. Слово можно заменить или предложить другое, пока его
        никто не начал отгадывать (слово 5 можно менять, пока никто не дошёл до него).
      </p>
      <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
        <thead>
          <tr style={{ textAlign: "left", opacity: 0.7 }}>
            <th style={thStyle}>№</th>
            <th style={thStyle}>Слово</th>
            <th style={thStyle}>Длина</th>
            <th style={thStyle}>Игроки</th>
            <th style={thStyle}></th>
          </tr>
        </thead>
        <tbody>
          {words.map((w) => (
            <tr key={w.id} style={{ borderTop: "1px solid #2a2a2c" }}>
              <td style={tdStyle}>{w.day_number}</td>
              <td style={{ ...tdStyle, textTransform: "uppercase", letterSpacing: 1, fontWeight: 700 }}>
                {w.word}
                <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 400, letterSpacing: 0, textTransform: "none", opacity: 0.6 }}>
                  {w.status === "confirmed" ? "подтверждено" : "предложено системой"}
                </span>
              </td>
              <td style={tdStyle}>{w.length} букв</td>
              <td style={{ ...tdStyle, opacity: 0.8 }}>начали {w.started} · прошли {w.finished}</td>
              <td style={tdStyle}>
                {w.editable ? (
                  <WordActions
                    compact word={w.word} length={w.length} onLength={(n) => handleLength(w, n)}
                    onReroll={() => handleReroll(w)} onReplace={(text) => handleReplace(w, text)}
                  />
                ) : (
                  <span style={{ fontSize: 12, opacity: 0.6 }}>уже начато — менять поздно</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}

export function MarathonIndividualWordsPanel({ tournament, onTournamentChanged }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [players, setPlayers] = useState(null);
  const [error, setError] = useState("");
  const [showWords, setShowWords] = useState(false); // по умолчанию слова скрыты
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(null); // { entryId, wordId } | null
  const [busy, setBusy] = useState(false);
  const [hoveredWordId, setHoveredWordId] = useState(null); // слово, над которым курсор (показ попыток)

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/marathon/individual-words`);
      if (tournamentIdRef.current === id) {
        setPlayers(data);
        setError("");
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    setPlayers(null);
    setSelected(null);
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id, tournament.words_count, tournament.individual_words]);

  async function run(action) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      await refresh();
    }
  }

  const selectedPlayer = selected && players ? players.find((p) => p.entry_id === selected.entryId) : null;
  const selectedWord = selectedPlayer ? selectedPlayer.words.find((w) => w.id === selected.wordId) : null;

  function handleReroll(w) {
    return run(() => api(`/api/admin/words/${w.id}/reroll`, { method: "POST" }));
  }

  // Длина слова с номером `number` — сразу у всех игроков, которые это слово ещё не начали.
  function handleColumnLength(number, length) {
    if (length == null) return;
    return run(async () => {
      await api(`/api/admin/tournaments/${tournament.id}/marathon/word-length?number=${number}`, {
        method: "POST", body: JSON.stringify({ length }),
      });
      if (onTournamentChanged) await onTournamentChanged();
    });
  }

  function handleReplace(w, text) {
    return run(async () => {
      await api(`/api/admin/words/${w.id}/confirm`, { method: "POST", body: JSON.stringify({ override_word: text }) });
    });
  }

  async function handleRegeneratePlayer(p) {
    if (!await askConfirm(`Заново подобрать все ещё не начатые слова игрока ${p.callsign}?`)) return;
    return run(() => api(`/api/admin/tournaments/${tournament.id}/marathon/individual-words/${p.entry_id}/regenerate`, { method: "POST" }));
  }

  if (!players) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  const q = query.trim().toLowerCase();
  const shown = q ? players.filter((p) => p.callsign.toLowerCase().includes(q)) : players;
  const count = tournament.words_count || 0;
  const STATE_STYLE = {
    new: { border: "1px solid #3a3a3c", background: "transparent" },
    started: { border: "1px solid #b59f3b", background: "rgba(181,159,59,0.15)" },
    finished: { border: "1px solid #538d4e", background: "rgba(83,141,78,0.18)" },
  };
  const STATE_TITLE = { new: "не начато — можно менять", started: "идёт — менять поздно", finished: "пройдено — менять поздно" };
  const cellText = (w) => (showWords ? w.word : "•".repeat(w.length || 5));
  const columnLength = (i) => (tournament.word_plan?.marathon?.[i]) ?? tournament.word_length ?? 5;

  return (
    <div style={{ ...panelStyle, marginTop: 20, border: "1px solid #b59f3b" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Слова марафона — у каждого свои</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={() => setShowWords((v) => !v)} style={ghostButtonStyle}>
            {showWords ? "Скрыть слова" : "Показать слова"}
          </button>
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      <p style={{ fontSize: 13, opacity: 0.7 }}>
        Это ответы — не показывайте этот экран участникам. У каждого игрока свой набор из {count} слов; слово можно
        заменить, пока этот игрок его не начал. Длину слова (5–7 букв) можно задать в шапке столбца — она
        сменится у всех, кто это слово ещё не начал. Автоматически подобранные слова не повторяются между игроками, при
        ручной замене повторы допустимы. Нажмите на ячейку, чтобы изменить слово.
      </p>
      {players.length === 0 ? (
        <div style={{ opacity: 0.7, fontSize: 13 }}>Пока нет подключённых игроков.</div>
      ) : (
        <>
          <input
            placeholder="Найти игрока по позывному" value={query} onChange={(e) => setQuery(e.target.value)}
            style={{ ...inputStyle, marginBottom: 8, maxWidth: 260 }}
          />
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "separate", borderSpacing: 0, fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", opacity: 0.7 }}>
                  <th style={{ ...thStyle, position: "sticky", left: 0, background: "#1c1c1e", zIndex: 1 }}>Игрок</th>
                  {Array.from({ length: count }, (_, i) => (
                    <th key={i} style={{ ...thStyle, textAlign: "center" }}>
                      {i + 1}
                      <div>
                        <LengthSelect
                          value={columnLength(i)} disabled={busy}
                          onChange={(n) => handleColumnLength(i + 1, n)}
                          title={`Длина слова №${i + 1} у всех игроков, которые его ещё не начали`}
                          style={{ fontSize: 11, padding: "1px 2px" }}
                        />
                      </div>
                    </th>
                  ))}
                  <th style={thStyle}></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((p) => (
                  <tr key={p.entry_id}>
                    <td style={{ ...tdStyle, position: "sticky", left: 0, background: "#1c1c1e", whiteSpace: "nowrap" }}>{p.callsign}</td>
                    {p.words.map((w) => {
                      const isSel = selected && selected.wordId === w.id;
                      return (
                        <td
                          key={w.id} style={{ ...tdStyle, position: "relative" }}
                          onMouseEnter={() => { if (w.guesses && w.guesses.length > 0) setHoveredWordId(w.id); }}
                          onMouseLeave={() => setHoveredWordId(null)}
                        >
                          <button
                            onClick={() => setSelected({ entryId: p.entry_id, wordId: w.id })}
                            title={w.guesses && w.guesses.length > 0 ? undefined : STATE_TITLE[w.state]}
                            style={{
                              ...STATE_STYLE[w.state], borderRadius: 4, padding: "3px 8px", color: "inherit", cursor: "pointer",
                              textTransform: "uppercase", letterSpacing: 1, fontSize: 12, minWidth: 64,
                              outline: isSel ? "2px solid #e5e5e5" : "none",
                            }}
                          >
                            {cellText(w)}
                          </button>
                          {hoveredWordId === w.id && <GuessesPopup guesses={w.guesses} />}
                        </td>
                      );
                    })}
                    <td style={tdStyle}>
                      <button
                        onClick={() => handleRegeneratePlayer(p)} disabled={busy}
                        style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11, whiteSpace: "nowrap" }}
                      >
                        Перегенерировать набор
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 11, opacity: 0.6, marginTop: 6 }}>
            Цвет ячейки: серая — не начато, жёлтая — идёт, зелёная — пройдено.
          </div>
          {selectedWord && (
            <div style={{ marginTop: 12, padding: 10, border: "1px solid #3a3a3c", borderRadius: 6 }}>
              <div style={{ marginBottom: 8 }}>
                {selectedPlayer.callsign} · слово {selectedWord.day_number}:{" "}
                <b style={{ textTransform: "uppercase", letterSpacing: 1 }}>{cellText(selectedWord)}</b>{" "}
                <span style={{ fontSize: 12, opacity: 0.6 }}>({STATE_TITLE[selectedWord.state]})</span>
              </div>
              {selectedWord.editable ? (
                <WordActions
                  word={selectedWord.word} onReroll={() => handleReroll(selectedWord)} onReplace={(text) => handleReplace(selectedWord, text)}
                >
                  <button onClick={() => setSelected(null)} style={{ ...ghostButtonStyle, fontSize: 12 }}>Закрыть</button>
                </WordActions>
              ) : (
                <div style={{ fontSize: 12, opacity: 0.7 }}>
                  Это слово уже начато этим игроком — менять поздно.{" "}
                  <button onClick={() => setSelected(null)} style={{ ...ghostButtonStyle, fontSize: 12 }}>Закрыть</button>
                </div>
              )}
            </div>
          )}
        </>
      )}
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}
