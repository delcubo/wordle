import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

const DEFAULT_SCORING = { "1": 10, "2": 5, "3": 4, "4": 3, "5": 2, "6": 1 };
const TYPE_LABEL = { standard: "Стандартный", knockout: "На вылет", championship: "Чемпионат", endless: "Бессрочная игра" };
const STATUS_LABEL = { draft: "черновик", active: "идёт", tiebreak: "тай-брейк", playoff: "плей-офф", finished: "завершён" };

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Ошибка запроса");
  }
  return res.json();
}

export default function AdminDashboard() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("tournaments");
  const [tournaments, setTournaments] = useState([]);
  const [users, setUsers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  async function refreshTournaments() {
    const data = await api("/api/admin/tournaments");
    setTournaments(data);
    setSelected((prev) => prev ? data.find((t) => t.id === prev.id) || data[0] || null : data[0] || null);
  }

  async function refreshUsers() {
    setUsers(await api("/api/admin/users"));
  }

  useEffect(() => {
    api("/api/admin/me")
      .then(() => Promise.all([refreshTournaments(), refreshUsers()]))
      .catch(() => {})
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleLogout() {
    await api("/api/admin/logout", { method: "POST" });
    navigate("/login");
  }

  if (loading) return <Centered>Загрузка...</Centered>;

  return (
    <div style={{ minHeight: "100vh", background: "#121213", color: "#fff", fontFamily: "system-ui, sans-serif", padding: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Админ-панель · Вордли</h1>
        <button onClick={handleLogout} style={ghostButtonStyle}>Выйти</button>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <TabButton active={tab === "tournaments"} onClick={() => setTab("tournaments")}>Розыгрыши</TabButton>
        <TabButton active={tab === "users"} onClick={() => setTab("users")}>Игроки</TabButton>
      </div>

      {tab === "users" && <UsersPanel users={users} onChanged={refreshUsers} />}

      {tab === "tournaments" && (
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 300px" }}>
            <TournamentPanel
              tournaments={tournaments}
              selected={selected}
              onSelect={setSelected}
              onCreated={refreshTournaments}
              onActivated={refreshTournaments}
            />
          </div>
          <div style={{ flex: "2 1 500px" }}>
            {selected ? (
              <>
                <EntriesPanel tournament={selected} users={users} />
                <WordConfirmPanel tournament={selected} />
                {selected.duration_days != null && <StandingsPanel tournament={selected} />}
                {selected.type === "championship" && <TiebreakPanel tournament={selected} />}
                {(selected.type === "championship" || selected.type === "knockout") && (
                  <BracketPanel tournament={selected} />
                )}
              </>
            ) : (
              <div style={{ opacity: 0.7 }}>Создайте розыгрыш, чтобы начать.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        ...ghostButtonStyle,
        background: active ? "#2a2a2c" : "transparent",
        borderColor: active ? "#538d4e" : "#3a3a3c",
      }}
    >
      {children}
    </button>
  );
}

function UsersPanel({ users, onChanged }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState(null);

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    try {
      await api("/api/admin/users", { method: "POST", body: JSON.stringify({ admin_note: note || null }) });
      setNote("");
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  function linkFor(token) {
    return `${window.location.origin}/play/${token}`;
  }

  function copyLink(u) {
    navigator.clipboard?.writeText(linkFor(u.access_token));
    setCopiedId(u.id);
    setTimeout(() => setCopiedId(null), 1500);
  }

  return (
    <div style={{ ...panelStyle, maxWidth: 600 }}>
      <h3 style={{ marginTop: 0 }}>Игроки</h3>
      <p style={{ opacity: 0.7, fontSize: 13, marginTop: -4 }}>
        Каждый игрок регистрируется один раз и получает одну постоянную ссылку —
        дальше его можно подключать к любому числу розыгрышей.
      </p>
      <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          placeholder="Заметка (кто это), опционально"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button type="submit" style={buttonStyle}>+ Новый игрок</button>
      </form>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", opacity: 0.7, fontSize: 13 }}>
            <th style={thStyle}>Заметка</th>
            <th style={thStyle}>Ссылка</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} style={{ borderTop: "1px solid #2a2a2c" }}>
              <td style={tdStyle}>{u.admin_note || `Игрок #${u.id}`}</td>
              <td style={tdStyle}>
                <button onClick={() => copyLink(u)} style={ghostButtonStyle}>
                  {copiedId === u.id ? "Скопировано!" : "Копировать ссылку"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TournamentPanel({ tournaments, selected, onSelect, onCreated, onActivated }) {
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [type, setType] = useState("standard");
  const [startDate, setStartDate] = useState("");
  const [duration, setDuration] = useState(20);
  const [bracketSize, setBracketSize] = useState(16);
  const [error, setError] = useState("");

  const needsDuration = type === "standard" || type === "championship";
  const needsBracket = type === "knockout" || type === "championship";

  async function handleCreate(e) {
    e.preventDefault();
    setError("");
    try {
      await api("/api/admin/tournaments", {
        method: "POST",
        body: JSON.stringify({
          title,
          type,
          start_date: startDate,
          duration_days: needsDuration ? Number(duration) : null,
          scoring_rules: DEFAULT_SCORING,
          skip_flag_symbol: "🚩",
          bracket_size: needsBracket ? Number(bracketSize) : null,
          rounds_per_match: 1,
        }),
      });
      setShowForm(false);
      setTitle("");
      setStartDate("");
      onCreated();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleActivate(id) {
    await api(`/api/admin/tournaments/${id}/activate`, { method: "POST" });
    onActivated();
  }

  return (
    <div style={panelStyle}>
      <h3 style={{ marginTop: 0 }}>Розыгрыши</h3>
      {tournaments.map((t) => (
        <div
          key={t.id}
          onClick={() => onSelect(t)}
          style={{
            padding: 8,
            borderRadius: 6,
            marginBottom: 6,
            cursor: "pointer",
            background: selected?.id === t.id ? "#2a2a2c" : "transparent",
            border: "1px solid #3a3a3c",
          }}
        >
          <div style={{ fontWeight: 600 }}>{t.title}</div>
          <div style={{ fontSize: 13, opacity: 0.7 }}>
            {TYPE_LABEL[t.type] || t.type} · {t.start_date}
            {t.duration_days != null ? ` · ${t.duration_days} дн.` : ""} · {STATUS_LABEL[t.status] || t.status}
          </div>
          {t.status !== "active" && (
            <button
              onClick={(e) => { e.stopPropagation(); handleActivate(t.id); }}
              style={{ ...ghostButtonStyle, marginTop: 6, fontSize: 12 }}
            >
              Активировать
            </button>
          )}
        </div>
      ))}

      {!showForm ? (
        <button onClick={() => setShowForm(true)} style={buttonStyle}>+ Новый розыгрыш</button>
      ) : (
        <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
          <input placeholder="Название" value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle} required />
          <select value={type} onChange={(e) => setType(e.target.value)} style={inputStyle}>
            <option value="standard">Стандартный</option>
            <option value="championship">Чемпионат (+ плей-офф)</option>
            <option value="knockout">На вылет</option>
            <option value="endless">Бессрочная игра (без очков и таблицы)</option>
          </select>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={inputStyle} required />
          {needsDuration && (
            <input type="number" placeholder="Длительность (дней)" value={duration} onChange={(e) => setDuration(e.target.value)} style={inputStyle} required min={1} />
          )}
          {needsBracket && (
            <input type="number" placeholder="Размер сетки (степень двойки)" value={bracketSize} onChange={(e) => setBracketSize(e.target.value)} style={inputStyle} required min={2} />
          )}
          {error && <div style={{ color: "#e5484d" }}>{error}</div>}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" style={buttonStyle}>Создать</button>
            <button type="button" onClick={() => setShowForm(false)} style={ghostButtonStyle}>Отмена</button>
          </div>
        </form>
      )}
    </div>
  );
}

function EntriesPanel({ tournament, users }) {
  const [entries, setEntries] = useState([]);
  const [userId, setUserId] = useState("");
  const [callsign, setCallsign] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setEntries(await api(`/api/admin/tournaments/${tournament.id}/entries`));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  const connectedUserIds = new Set(entries.map((e) => e.user_id));
  const availableUsers = users.filter((u) => !connectedUserIds.has(u.id));

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/entries`, {
        method: "POST",
        body: JSON.stringify({ user_id: Number(userId), callsign }),
      });
      setUserId("");
      setCallsign("");
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div style={panelStyle}>
      <h3 style={{ marginTop: 0 }}>Участники «{tournament.title}»</h3>
      <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <select value={userId} onChange={(e) => setUserId(e.target.value)} style={inputStyle} required>
          <option value="" disabled>Выберите игрока</option>
          {availableUsers.map((u) => (
            <option key={u.id} value={u.id}>{u.admin_note || `Игрок #${u.id}`}</option>
          ))}
        </select>
        <input placeholder="Позывной для этого розыгрыша" value={callsign} onChange={(e) => setCallsign(e.target.value)} style={inputStyle} required />
        <button type="submit" style={buttonStyle}>Подключить</button>
      </form>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", opacity: 0.7, fontSize: 13 }}>
            <th style={thStyle}>Позывной</th>
            <th style={thStyle}>Игрок</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const u = users.find((x) => x.id === e.user_id);
            return (
              <tr key={e.id} style={{ borderTop: "1px solid #2a2a2c" }}>
                <td style={tdStyle}>{e.callsign}</td>
                <td style={{ ...tdStyle, opacity: 0.7 }}>{u?.admin_note || `Игрок #${e.user_id}`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function WordConfirmPanel({ tournament }) {
  const [word, setWord] = useState(null);
  const [override, setOverride] = useState("");
  const [error, setError] = useState("");
  const [notApplicable, setNotApplicable] = useState(false);

  async function refresh() {
    setError("");
    setNotApplicable(false);
    try {
      const data = await api(`/api/admin/tournaments/${tournament.id}/words/upcoming`);
      setWord(data);
    } catch (e) {
      setNotApplicable(true);
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  async function handleConfirm(useOverride) {
    setError("");
    try {
      const updated = await api(`/api/admin/words/${word.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ override_word: useOverride ? override.trim().toLowerCase() : null }),
      });
      setWord(updated);
      setOverride("");
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
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button onClick={() => handleConfirm(false)} style={buttonStyle}>Согласиться с этим словом</button>
        <button onClick={handleReroll} style={ghostButtonStyle}>Предложить другое слово</button>
        <input placeholder="Или ввести своё слово" value={override} onChange={(e) => setOverride(e.target.value)} style={inputStyle} maxLength={5} />
        <button onClick={() => handleConfirm(true)} disabled={override.trim().length !== 5} style={ghostButtonStyle}>Заменить</button>
      </div>
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}

function StandingsPanel({ tournament }) {
  const [standings, setStandings] = useState(null);

  async function refresh() {
    setStandings(await api(`/api/admin/tournaments/${tournament.id}/standings`));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  if (!standings) return null;

  return (
    <div style={{ ...panelStyle, marginTop: 20, overflowX: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ marginTop: 0 }}>Таблица</h3>
        <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
      </div>
      <table style={{ borderCollapse: "collapse", fontSize: 13, minWidth: 400 }}>
        <thead>
          <tr>
            <th style={thStyle}>#</th>
            <th style={thStyle}>Позывной</th>
            <th style={thStyle}>Σ</th>
            {Array.from({ length: standings.total_days }, (_, i) => (
              <th key={i} style={thStyle}>#{i + 1}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {standings.rows.map((r) => (
            <tr key={r.participant_id} style={{ borderTop: "1px solid #2a2a2c" }}>
              <td style={tdStyle}>{r.place}</td>
              <td style={tdStyle}>{r.callsign}</td>
              <td style={{ ...tdStyle, fontWeight: 700 }}>{r.total_points}</td>
              {r.daily.map((d, i) => (
                <td key={i} style={{ ...tdStyle, textAlign: "center" }}>
                  {d.played ? d.points : standings.skip_flag_symbol}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TiebreakPanel({ tournament }) {
  const [rounds, setRounds] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setRounds(await api(`/api/admin/tournaments/${tournament.id}/tiebreak`));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  async function handleStart() {
    setError("");
    try {
      const res = await api(`/api/admin/tournaments/${tournament.id}/tiebreak/start`, { method: "POST" });
      if (!res.started) setError("Тай-брейк не нужен — равных мест на границе сетки нет.");
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ marginTop: 0 }}>Тай-брейк</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleStart} style={buttonStyle}>Запустить тай-брейк</button>
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}
      {rounds && rounds.length === 0 && (
        <div style={{ opacity: 0.7, fontSize: 13 }}>
          Раундов пока нет — запустите тай-брейк после окончания основного этапа.
        </div>
      )}
      {rounds && rounds.map((r) => (
        <div key={r.id} style={{ border: "1px solid #3a3a3c", borderRadius: 6, padding: 10, marginTop: 8 }}>
          <div style={{ fontSize: 13, opacity: 0.7, marginBottom: 4 }}>
            Раунд {r.round_number}{r.previous_round_id ? ` (продолжение раунда #${r.previous_round_id})` : ""} ·{" "}
            слово: <b style={{ textTransform: "uppercase" }}>{r.word}</b> ·{" "}
            {r.completed ? "завершён" : "идёт"}
          </div>
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {r.participants.map((p) => (
                <tr key={p.entry_id}>
                  <td style={tdStyle}>{p.callsign}</td>
                  <td style={tdStyle}>
                    {p.attempts_used == null ? "ещё не играл" : `${p.solved ? "угадал" : "не угадал"} за ${p.attempts_used}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

const MATCH_STATUS_LABEL = { pending: "ожидает", in_progress: "идёт", finished: "завершён" };

function BracketPanel({ tournament }) {
  const [entries, setEntries] = useState([]);
  const [matches, setMatches] = useState(null);
  const [pairSelections, setPairSelections] = useState([]);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setMatches(await api(`/api/admin/tournaments/${tournament.id}/bracket`));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    api(`/api/admin/tournaments/${tournament.id}/entries`).then(setEntries).catch(() => {});
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

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
      const pairs = pairSelections.map((p) => [Number(p.a), Number(p.b)]);
      await api(`/api/admin/tournaments/${tournament.id}/bracket/round1`, {
        method: "POST",
        body: JSON.stringify({ pairs }),
      });
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

      {!bracketExists && tournament.type === "championship" && (
        <button onClick={handleGenerate} style={buttonStyle}>Сгенерировать сетку по итогам</button>
      )}

      {!bracketExists && tournament.type === "knockout" && (
        <form onSubmit={handleSubmitRound1} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {pairSelections.map((p, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ opacity: 0.7, fontSize: 13 }}>Пара {i + 1}:</span>
              <select value={p.a} onChange={(e) => updatePair(i, "a", e.target.value)} style={inputStyle} required>
                <option value="" disabled>Игрок A</option>
                {entries.map((en) => <option key={en.id} value={en.id}>{en.callsign}</option>)}
              </select>
              <select value={p.b} onChange={(e) => updatePair(i, "b", e.target.value)} style={inputStyle} required>
                <option value="" disabled>Игрок B</option>
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
              {matches.map((m) => (
                <tr key={m.id} style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={tdStyle}>Р{m.round_number} · пара {m.position + 1}</td>
                  <td style={tdStyle}>{m.entry_a_callsign || "?"}</td>
                  <td style={tdStyle}>—</td>
                  <td style={tdStyle}>{m.entry_b_callsign || "?"}</td>
                  <td style={{ ...tdStyle, opacity: 0.7 }}>
                    {m.winner_entry_id
                      ? `победил: ${m.winner_entry_id === m.entry_a_id ? m.entry_a_callsign : m.entry_b_callsign}`
                      : MATCH_STATUS_LABEL[m.status] || m.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <BracketImage tournament={tournament} matches={matches} />
        </>
      )}
    </div>
  );
}

const BOX_W = 170;
const BOX_H = 44;
const GAP_Y = 18;
const COL_GAP = 70;
const PAD = 24;

function roundLabel(matchesInRound) {
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

function BracketImage({ tournament, matches }) {
  const svgRef = useRef(null);
  const [status, setStatus] = useState("");

  const totalRounds = Math.round(Math.log2(tournament.bracket_size));
  const matchByKey = new Map(matches.map((m) => [`${m.round_number}:${m.position}`, m]));

  const rounds = [];
  for (let r = 1; r <= totalRounds; r++) {
    const count = tournament.bracket_size / 2 ** r;
    rounds.push(Array.from({ length: count }, (_, p) => matchByKey.get(`${r}:${p}`) || null));
  }

  const centers = [rounds[0].map((_, i) => PAD + i * (BOX_H + GAP_Y) + BOX_H / 2)];
  for (let r = 1; r < rounds.length; r++) {
    centers.push(rounds[r].map((_, i) => (centers[r - 1][2 * i] + centers[r - 1][2 * i + 1]) / 2));
  }

  const svgHeight = Math.max(...centers[0]) + BOX_H / 2 + PAD;
  const svgWidth = totalRounds * (BOX_W + COL_GAP) + PAD;

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
      <div style={{ overflowX: "auto", background: "#121213", borderRadius: 8, padding: 8 }}>
        <svg ref={svgRef} width={svgWidth} height={svgHeight} viewBox={`0 0 ${svgWidth} ${svgHeight}`}>
          <rect x={0} y={0} width={svgWidth} height={svgHeight} fill="#121213" />
          {rounds.map((slots, rIdx) => {
            const x = PAD + rIdx * (BOX_W + COL_GAP);
            return (
              <g key={`round-${rIdx}`}>
                <text x={x + BOX_W / 2} y={PAD - 8} textAnchor="middle" fontSize="12" fill="#818384">
                  {roundLabel(slots.length)}
                </text>
                {slots.map((m, i) => {
                  const y = centers[rIdx][i] - BOX_H / 2;
                  const nameA = m?.entry_a_callsign || "?";
                  const nameB = m?.entry_b_callsign || "?";
                  const winnerA = m?.winner_entry_id != null && m.winner_entry_id === m.entry_a_id;
                  const winnerB = m?.winner_entry_id != null && m.winner_entry_id === m.entry_b_id;
                  return (
                    <g key={`box-${rIdx}-${i}`}>
                      <rect x={x} y={y} width={BOX_W} height={BOX_H} rx={6} fill="#1c1c1e" stroke="#3a3a3c" />
                      <line x1={x} y1={y + BOX_H / 2} x2={x + BOX_W} y2={y + BOX_H / 2} stroke="#3a3a3c" />
                      <text x={x + 8} y={y + BOX_H / 2 - 6} fontSize="13" fill={winnerA ? "#6aaa64" : "#fff"} fontWeight={winnerA ? "700" : "400"}>
                        {nameA}
                      </text>
                      <text x={x + 8} y={y + BOX_H - 6} fontSize="13" fill={winnerB ? "#6aaa64" : "#fff"} fontWeight={winnerB ? "700" : "400"}>
                        {nameB}
                      </text>
                    </g>
                  );
                })}
              </g>
            );
          })}
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
                  stroke="#3a3a3c"
                />
              );
            });
          })}
        </svg>
      </div>
    </div>
  );
}

function Centered({ children }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#121213", color: "#fff" }}>
      {children}
    </div>
  );
}

const panelStyle = { background: "#1c1c1e", borderRadius: 10, padding: 16 };
const inputStyle = { padding: "8px 10px", borderRadius: 6, border: "1px solid #3a3a3c", background: "#121213", color: "#fff", fontSize: 14 };
const buttonStyle = { padding: "8px 12px", borderRadius: 6, border: "none", background: "#538d4e", color: "#fff", fontSize: 14, cursor: "pointer" };
const ghostButtonStyle = { padding: "6px 10px", borderRadius: 6, border: "1px solid #3a3a3c", background: "transparent", color: "#fff", fontSize: 13, cursor: "pointer" };
const thStyle = { padding: "4px 8px", textAlign: "left" };
const tdStyle = { padding: "4px 8px" };
