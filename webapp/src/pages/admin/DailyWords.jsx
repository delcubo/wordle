import { useEffect, useState } from "react";
import { api, ghostButtonStyle, panelStyle, tdStyle, thStyle, useLatest } from "../adminShared.jsx";
import WordActions from "../WordActions.jsx";

// Бонусные слова Стандартного режима и основного этапа Чемпионата (api/bonus.py): слово на каждый блок
// из N дней; открывается игроку без пропусков в блоке после слова последнего дня блока — на этот день.
export function BonusWordsPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [words, setWords] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/bonus-words`);
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
  }, [tournament.id, tournament.bonus_enabled, tournament.bonus_every_days, tournament.duration_days]);

  async function call(path, body) {
    const id = tournament.id;
    setError("");
    setBusy(true);
    try {
      const res = await api(`/api/admin/tournaments/${id}/bonus-words/${path}`, {
        method: "POST", body: body ? JSON.stringify(body) : undefined,
      });
      if (tournamentIdRef.current === id) setWords(res);
    } catch (e) {
      setError(e.message);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  if (!words) return error ? <div style={{ ...panelStyle, marginTop: 20, color: "#e5484d" }}>{error}</div> : null;

  return (
    <div style={{ ...panelStyle, marginTop: 20, border: "1px solid #e5a94c" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Бонусные слова</h3>
        <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
      </div>
      <p style={{ fontSize: 13, opacity: 0.7 }}>
        Бонус открывается игроку, у которого нет пропусков в блоке из {tournament.bonus_every_days} дн., сразу после слова
        последнего дня блока и доступен только в этот день; очки — по шкале розыгрыша. Слово и его длину можно менять, пока
        его никто не начал.
      </p>
      {words.length === 0 ? (
        <div style={{ fontSize: 13, opacity: 0.7 }}>При такой длительности и N бонусных слов нет.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th style={thStyle}>Бонус</th>
                <th style={thStyle}>Дни блока</th>
                <th style={thStyle}>Открывается</th>
                <th style={thStyle}>Слово</th>
                <th style={thStyle}>Игроки</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {words.map((w) => (
                <tr key={w.number} style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={{ ...tdStyle, fontWeight: 700 }}>Б{w.number}</td>
                  <td style={tdStyle}>{w.block_start}–{w.opening_day}</td>
                  <td style={tdStyle}>день {w.opening_day} · {w.calendar_date}</td>
                  <td style={{ ...tdStyle, textTransform: "uppercase", letterSpacing: 1, fontWeight: 700 }}>
                    {w.word}
                    <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 400, letterSpacing: 0, textTransform: "none", opacity: 0.6 }}>
                      {w.status === "confirmed" ? "подтверждено" : "предложено системой"}
                    </span>
                  </td>
                  <td style={{ ...tdStyle, opacity: 0.8 }}>право: {w.eligible} · сыграли: {w.played}</td>
                  <td style={tdStyle}>
                    {w.editable ? (
                      <WordActions
                        compact word={w.word} length={w.length} disabled={busy}
                        onLength={(n) => call(`${w.number}/length`, { length: n })}
                        onReroll={() => call(`${w.number}/reroll`)}
                        onReplace={(text) => call(`${w.number}`, { word: text })}
                      />
                    ) : (
                      <span style={{ fontSize: 12, opacity: 0.6 }}>уже начато — менять поздно</span>
                    )}
                  </td>
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

export function TodayWordPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [word, setWord] = useState(null);
  const [notApplicable, setNotApplicable] = useState(false);
  const [excluded, setExcluded] = useState(false);
  const [yesterday, setYesterday] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/words/today`);
      if (tournamentIdRef.current !== id) return;
      setWord(data);
      setExcluded(false);
      setNotApplicable(false);
      // В бессрочной игре дополнительно показываем вчерашнее слово прямо тут —
      // у неё нет фиксированного диапазона дней, чтобы держать это в истории
      // "по умолчанию" (см. пункт бэклога: вчера/сегодня/завтра).
      if (tournament.type === "endless" && data.day_number > 1) {
        const history = await api(`/api/admin/tournaments/${id}/words`);
        if (tournamentIdRef.current !== id) return;
        setYesterday(history.find((w) => w.day_number === data.day_number - 1) || null);
      } else {
        setYesterday(null);
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setNotApplicable(true);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  async function handleExclude() {
    await api("/api/admin/dictionary/excluded", { method: "POST", body: JSON.stringify({ word: word.word }) });
    setExcluded(true);
  }

  // Замена слова сегодняшнего дня — только в бессрочной игре и пока никто не
  // начал партию (word.editable приходит с сервера, он же перепроверяет).
  async function handleChange(path, body) {
    setError("");
    try {
      await api(path, { method: "POST", ...(body ? { body: JSON.stringify(body) } : {}) });
      setExcluded(false);
      await refresh();
    } catch (e) {
      setError(e.message);
      await refresh();
    }
  }

  if (notApplicable || !word) return null;

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <h3 style={{ marginTop: 0 }}>Слово сегодня — день {word.day_number} ({word.calendar_date})</h3>
      <p style={{ fontSize: 13, opacity: 0.7, marginTop: -4 }}>
        {word.editable
          ? "Слово можно заменить, пока никто не начал играть — после первой догадки любого игрока оно блокируется."
          : "День уже идёт, менять слово поздно — это просто справка для админа."}
      </p>
      {yesterday && (
        <div style={{ fontSize: 13, opacity: 0.6, marginBottom: 8 }}>
          Вчера (день {yesterday.day_number}): <b style={{ textTransform: "uppercase", letterSpacing: 1 }}>{yesterday.word}</b>
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 22, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2 }}>{word.word}</span>
        {!word.editable && (
          <button
            onClick={handleExclude}
            disabled={excluded}
            title="Больше не предлагать это слово в будущем — на сегодняшнее слово не влияет"
            style={{ ...ghostButtonStyle, fontSize: 12 }}
          >
            {excluded ? "Исключено из будущих слов" : "🚫 Исключить из словаря"}
          </button>
        )}
      </div>
      {word.editable && (
        <div style={{ marginTop: 10 }}>
          <WordActions
            word={word.word}
            onReroll={() => handleChange(`/api/admin/words/${word.id}/reroll`)}
            onReplace={(text) => handleChange(`/api/admin/words/${word.id}/confirm`, { override_word: text })}
          />
        </div>
      )}
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}

export function WordConfirmPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [word, setWord] = useState(null);
  const [error, setError] = useState("");
  const [notApplicable, setNotApplicable] = useState(false);

  async function refresh() {
    const id = tournament.id;
    setError("");
    setNotApplicable(false);
    try {
      const data = await api(`/api/admin/tournaments/${id}/words/upcoming`);
      if (tournamentIdRef.current === id) setWord(data);
    } catch (e) {
      if (tournamentIdRef.current === id) {
        setNotApplicable(true);
        setError(e.message);
      }
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  async function handleConfirm(useOverride, text) {
    setError("");
    try {
      const updated = await api(`/api/admin/words/${word.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ override_word: useOverride ? text : null }),
      });
      setWord(updated);
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleReroll() {
    setError("");
    try {
      const updated = await api(`/api/admin/words/${word.id}/reroll`, { method: "POST" });
      setWord(updated);
    } catch (e) {
      setError(e.message);
    }
  }

  if (notApplicable) return null;
  if (!word) return null;

  return (
    <div style={{ ...panelStyle, marginTop: 20, border: "1px solid #b59f3b" }}>
      <h3 style={{ marginTop: 0 }}>Слово на день {word.day_number} ({word.calendar_date})</h3>
      <p style={{ fontSize: 13, opacity: 0.7 }}>
        Это ответ дня — не показывайте этот экран участникам. Если не подтвердите
        вручную, предложенное слово станет действующим автоматически в начале дня.
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
        <span style={{ fontSize: 22, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2 }}>{word.word}</span>
        <span style={{ fontSize: 12, padding: "2px 8px", borderRadius: 4, background: word.status === "confirmed" ? "#538d4e" : "#3a3a3c" }}>
          {word.status === "confirmed" ? "подтверждено" : "предложено системой"}
        </span>
      </div>
      <WordActions
        word={word.word} onConfirm={() => handleConfirm(false)} onReroll={handleReroll}
        onReplace={(text) => handleConfirm(true, text)}
      />
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}

export function WordHistoryPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [words, setWords] = useState(null);
  const [open, setOpen] = useState(false);

  async function refresh() {
    const id = tournament.id;
    const data = await api(`/api/admin/tournaments/${id}/words`);
    if (tournamentIdRef.current === id) setWords(data);
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  if (!words) return null;
  const sorted = [...words].sort((a, b) => b.day_number - a.day_number);
  // В бессрочном режиме у розыгрыша нет конца, и список слов со временем рос
  // бы бесконечно — показываем только последние 10 дней (данные за остальные
  // никуда не деваются, просто не выводятся здесь).
  const shown = tournament.type === "endless" ? sorted.slice(0, 10) : sorted;

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        <h3 style={{ margin: 0 }}>
          История слов {tournament.type === "endless" && "(последние 10)"} {open ? "▾" : "▸"}
        </h3>
        <button onClick={(e) => { e.stopPropagation(); refresh(); }} style={ghostButtonStyle}>Обновить</button>
      </div>
      {open && (
        <table style={{ borderCollapse: "collapse", fontSize: 13, marginTop: 8, width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left", opacity: 0.7 }}>
              <th style={thStyle}>День</th>
              <th style={thStyle}>Дата</th>
              <th style={thStyle}>Слово</th>
              <th style={thStyle}>Статус</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((w) => (
              <tr key={w.id} style={{ borderTop: "1px solid #2a2a2c" }}>
                <td style={tdStyle}>{w.day_number}</td>
                <td style={tdStyle}>{w.calendar_date}</td>
                <td style={{ ...tdStyle, textTransform: "uppercase" }}>{w.word}</td>
                <td style={{ ...tdStyle, opacity: 0.7 }}>{w.status === "confirmed" ? "подтверждено" : "предложено"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
