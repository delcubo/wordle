import { Fragment, useEffect, useRef, useState } from "react";
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
  const [theme, setTheme] = useState("dark");

  async function refreshTournaments() {
    const data = await api("/api/admin/tournaments");
    setTournaments(data);
    setSelected((prev) => prev ? data.find((t) => t.id === prev.id) || data[0] || null : data[0] || null);
  }

  async function refreshUsers() {
    setUsers(await api("/api/admin/users"));
  }

  async function refreshTheme() {
    setTheme((await api("/api/admin/settings/theme")).theme);
  }

  useEffect(() => {
    api("/api/admin/me")
      .then(() => Promise.all([refreshTournaments(), refreshUsers(), refreshTheme()]))
      .catch(() => {})
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleLogout() {
    await api("/api/admin/logout", { method: "POST" });
    navigate("/login");
  }

  async function handleToggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    await api("/api/admin/settings/theme", { method: "PATCH", body: JSON.stringify({ theme: next }) });
    setTheme(next);
  }

  if (loading) return <Centered>Загрузка...</Centered>;

  return (
    <div style={{ minHeight: "100vh", background: "#121213", color: "#fff", fontFamily: "system-ui, sans-serif" }}>
      <div style={{ position: "sticky", top: 0, zIndex: 10, background: "#121213", padding: "20px 20px 0", borderBottom: "1px solid #2a2a2c" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h1 style={{ margin: 0 }}>Админ-панель · Вордли</h1>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button onClick={handleToggleTheme} style={ghostButtonStyle} title="Тема оформления для игроков (не влияет на саму админ-панель)">
              Тема игроков: {theme === "dark" ? "тёмная" : "светлая"}
            </button>
            <button onClick={handleLogout} style={ghostButtonStyle}>Выйти</button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, paddingBottom: 12 }}>
          <TabButton active={tab === "tournaments"} onClick={() => setTab("tournaments")}>Розыгрыши</TabButton>
          <TabButton active={tab === "users"} onClick={() => setTab("users")}>Игроки</TabButton>
          <TabButton active={tab === "dictionary"} onClick={() => setTab("dictionary")}>Словарь</TabButton>
        </div>
      </div>

      <div style={{ padding: 20 }}>
      {tab === "users" && <UsersPanel users={users} onChanged={refreshUsers} />}
      {tab === "dictionary" && <DictionaryPanel />}

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
                {selected.type !== "knockout" && <TodayWordPanel tournament={selected} />}
                <WordConfirmPanel tournament={selected} />
                {selected.type !== "knockout" && <WordHistoryPanel tournament={selected} />}
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

function userLabel(u) {
  return u.admin_note || `Игрок #${u.id}`;
}

function UsersPanel({ users, onChanged }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  const [editingNoteId, setEditingNoteId] = useState(null);
  const [noteForm, setNoteForm] = useState("");
  const [search, setSearch] = useState("");

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

  async function saveNote(u) {
    setError("");
    try {
      await api(`/api/admin/users/${u.id}`, {
        method: "PATCH",
        body: JSON.stringify({ admin_note: noteForm.trim() || null }),
      });
      setEditingNoteId(null);
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleDisconnect(u) {
    if (!window.confirm(
      `Отключить «${u.admin_note || `Игрок #${u.id}`}» от всех розыгрышей? ` +
      `Личная ссылка продолжит работать, статистика сохранится.`
    )) {
      return;
    }
    await api(`/api/admin/users/${u.id}/disconnect`, { method: "POST" });
    onChanged();
  }

  async function handleArchive(u) {
    if (!window.confirm(
      `Переместить «${u.admin_note || `Игрок #${u.id}`}» в архив? Личная ссылка перестанет работать, ` +
      `игрок отключится от всех розыгрышей, но набранная статистика сохранится.`
    )) {
      return;
    }
    await api(`/api/admin/users/${u.id}/archive`, { method: "PATCH", body: JSON.stringify({ archived: true }) });
    onChanged();
  }

  async function handleRestore(u) {
    await api(`/api/admin/users/${u.id}/archive`, { method: "PATCH", body: JSON.stringify({ archived: false }) });
    onChanged();
  }

  async function handleRegenerateLink(u) {
    if (!window.confirm(
      `Выдать новую ссылку «${u.admin_note || `Игрок #${u.id}`}»? Старая ссылка сразу перестанет работать.`
    )) {
      return;
    }
    await api(`/api/admin/users/${u.id}/regenerate-link`, { method: "POST" });
    onChanged();
  }

  function renderRow(u) {
    const isEditingNote = editingNoteId === u.id;
    return (
      <tr key={u.id} style={{ borderTop: "1px solid #2a2a2c" }}>
        <td style={tdStyle}>
          {isEditingNote ? (
            <div style={{ display: "flex", gap: 4 }}>
              <input
                autoFocus
                value={noteForm}
                onChange={(e) => setNoteForm(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveNote(u); if (e.key === "Escape") setEditingNoteId(null); }}
                style={{ ...inputStyle, padding: "2px 6px", fontSize: 13 }}
              />
              <button onClick={() => saveNote(u)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
              <button onClick={() => setEditingNoteId(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
            </div>
          ) : (
            <>
              {u.admin_note || `Игрок #${u.id}`}
              <button
                onClick={() => { setEditingNoteId(u.id); setNoteForm(u.admin_note || ""); }}
                title="Изменить заметку"
                style={{ ...ghostButtonStyle, marginLeft: 6, padding: "0px 6px", fontSize: 11 }}
              >
                ✎
              </button>
            </>
          )}
        </td>
        <td style={{ ...tdStyle, fontSize: 12 }}>
          {u.tournaments.length === 0 ? (
            <span style={{ opacity: 0.5 }}>—</span>
          ) : (
            u.tournaments.map((t, i) => (
              <span key={t.tournament_id}>
                {i > 0 && ", "}
                <span style={{ opacity: t.active ? 1 : 0.5 }}>
                  {t.title}{!t.active && " (отключён)"}
                </span>
              </span>
            ))
          )}
        </td>
        <td style={tdStyle}>
          {!u.archived && (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              <button onClick={() => copyLink(u)} style={ghostButtonStyle}>
                {copiedId === u.id ? "Скопировано!" : "Копировать ссылку"}
              </button>
              <button onClick={() => handleRegenerateLink(u)} style={{ ...ghostButtonStyle, fontSize: 12 }} title="Выдать новую ссылку взамен утерянной">
                Новая ссылка
              </button>
            </div>
          )}
        </td>
        <td style={tdStyle}>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {u.archived ? (
              <button onClick={() => handleRestore(u)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                Восстановить
              </button>
            ) : (
              <>
                <button onClick={() => handleDisconnect(u)} style={{ ...ghostButtonStyle, fontSize: 12 }} title="Отключить от всех розыгрышей — ссылка продолжит работать">
                  Отключить
                </button>
                <button onClick={() => handleArchive(u)} style={{ ...ghostButtonStyle, fontSize: 12 }} title="В архив — ссылка перестанет работать">
                  В архив
                </button>
              </>
            )}
          </div>
        </td>
      </tr>
    );
  }

  const query = search.trim().toLowerCase();
  const matchesSearch = (u) => !query || userLabel(u).toLowerCase().includes(query);
  const byLabel = (a, b) => userLabel(a).localeCompare(userLabel(b), "ru");

  const activeUsers = users.filter((u) => !u.archived && matchesSearch(u)).sort(byLabel);
  const archivedUsers = users.filter((u) => u.archived && matchesSearch(u)).sort(byLabel);

  return (
    <div style={{ ...panelStyle, maxWidth: 700 }}>
      <h3 style={{ marginTop: 0 }}>Игроки</h3>
      <p style={{ opacity: 0.7, fontSize: 13, marginTop: -4 }}>
        Каждый игрок регистрируется один раз и получает одну постоянную ссылку —
        дальше его можно подключать к любому числу розыгрышей. Список отсортирован по алфавиту.
      </p>
      <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <input
          placeholder="Заметка (кто это), опционально"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button type="submit" style={buttonStyle}>+ Новый игрок</button>
      </form>
      <input
        placeholder="🔎 Поиск по заметке..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ ...inputStyle, width: "100%", marginBottom: 12, boxSizing: "border-box" }}
      />
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", opacity: 0.7, fontSize: 13 }}>
            <th style={thStyle}>Заметка</th>
            <th style={thStyle}>Розыгрыши</th>
            <th style={thStyle}>Ссылка</th>
            <th style={thStyle}></th>
          </tr>
        </thead>
        <tbody>{activeUsers.map(renderRow)}</tbody>
      </table>
      {query && activeUsers.length === 0 && (
        <div style={{ opacity: 0.5, fontSize: 13, marginTop: 8 }}>Никого не найдено.</div>
      )}

      {archivedUsers.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <button
            onClick={() => setShowArchived((v) => !v)}
            style={{ ...ghostButtonStyle, fontSize: 13 }}
          >
            {showArchived ? "▾" : "▸"} Архив ({archivedUsers.length})
          </button>
          {showArchived && (
            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
              <tbody>{archivedUsers.map(renderRow)}</tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function DictionaryPanel() {
  const [words, setWords] = useState([]);
  const [newWord, setNewWord] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setWords(await api("/api/admin/dictionary/excluded"));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    try {
      await api("/api/admin/dictionary/excluded", {
        method: "POST",
        body: JSON.stringify({ word: newWord.trim().toLowerCase() }),
      });
      setNewWord("");
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleRemove(id) {
    await api(`/api/admin/dictionary/excluded/${id}`, { method: "DELETE" });
    refresh();
  }

  return (
    <div style={{ ...panelStyle, maxWidth: 500 }}>
      <h3 style={{ marginTop: 0 }}>Словарь — исключённые слова</h3>
      <p style={{ opacity: 0.7, fontSize: 13, marginTop: -4 }}>
        Слова из этого списка больше не будут предлагаться как новое слово дня —
        удобно вычищать странные/архаичные находки по факту игры. На уже
        назначенные слова (в т.ч. сегодняшнее) и на проверку вводимых попыток
        не влияет.
      </p>
      <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          placeholder="Слово из 5 букв"
          value={newWord}
          onChange={(e) => setNewWord(e.target.value)}
          maxLength={20}
          style={{ ...inputStyle, flex: 1 }}
        />
        <button type="submit" style={buttonStyle}>Исключить</button>
      </form>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

      {words.length === 0 ? (
        <div style={{ opacity: 0.5, fontSize: 13 }}>Список пуст.</div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <tbody>
            {words.map((w) => (
              <tr key={w.id} style={{ borderTop: "1px solid #2a2a2c" }}>
                <td style={{ ...tdStyle, textTransform: "uppercase", letterSpacing: 1 }}>{w.word}</td>
                <td style={tdStyle}>
                  <button onClick={() => handleRemove(w.id)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                    Вернуть в словарь
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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
  const [hashtag, setHashtag] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [editingSettings, setEditingSettings] = useState(null); // id розыгрыша | null
  const [settingsForm, setSettingsForm] = useState({ title: "", duration_days: "", hashtag: "", note: "", start_date: "" });
  const [showArchive, setShowArchive] = useState(false);

  const todayIso = new Date().toISOString().slice(0, 10);

  function startEditSettings(t) {
    setError("");
    setEditingSettings(t.id);
    setSettingsForm({
      title: t.title, duration_days: t.duration_days ?? "", hashtag: t.hashtag || "",
      note: t.note || "", start_date: t.start_date,
    });
  }

  async function handleSaveSettings(t) {
    setError("");
    try {
      const body = { title: settingsForm.title, hashtag: settingsForm.hashtag, note: settingsForm.note };
      if (t.duration_days != null) body.duration_days = Number(settingsForm.duration_days);
      if (t.start_date >= todayIso && settingsForm.start_date !== t.start_date) {
        body.start_date = settingsForm.start_date;
      }
      await api(`/api/admin/tournaments/${t.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setEditingSettings(null);
      onCreated();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleTogglePause(t) {
    await api(`/api/admin/tournaments/${t.id}/pause`, { method: "PATCH", body: JSON.stringify({ paused: !t.paused }) });
    onActivated();
  }

  async function handleToggleArchived(t) {
    await api(`/api/admin/tournaments/${t.id}/archive`, { method: "PATCH", body: JSON.stringify({ archived: !t.archived }) });
    onActivated();
  }

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
          hashtag: hashtag.trim() || null,
          note: note.trim() || null,
        }),
      });
      setShowForm(false);
      setTitle("");
      setStartDate("");
      setHashtag("");
      setNote("");
      onCreated();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleActivate(id) {
    await api(`/api/admin/tournaments/${id}/activate`, { method: "POST" });
    onActivated();
  }

  function renderCard(t) {
    return (
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
        <div style={{ fontWeight: 600 }}>
          {t.title}
          {t.paused && (
            <span style={{ marginLeft: 6, fontSize: 11, color: "#e5a94c", border: "1px solid #e5a94c", borderRadius: 4, padding: "1px 5px" }}>
              приостановлен
            </span>
          )}
        </div>
        <div style={{ fontSize: 13, opacity: 0.7 }}>
          {TYPE_LABEL[t.type] || t.type} · {t.start_date}
          {t.duration_days != null ? ` · ${t.duration_days} дн.` : ""} · {STATUS_LABEL[t.status] || t.status}
        </div>
        {t.note && editingSettings !== t.id && (
          <div style={{ fontSize: 12, opacity: 0.6, marginTop: 4, whiteSpace: "pre-wrap" }}>{t.note}</div>
        )}
        {editingSettings === t.id ? (
          <div onClick={(e) => e.stopPropagation()} style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
            <input
              value={settingsForm.title}
              onChange={(e) => setSettingsForm((f) => ({ ...f, title: e.target.value }))}
              placeholder="Название (день/стадия добавляются автоматически)"
              style={{ ...inputStyle, fontSize: 12, padding: "4px 6px" }}
            />
            {t.start_date >= todayIso && (
              <label style={{ fontSize: 11, opacity: 0.7 }}>
                Дата старта (розыгрыш ещё не начался)
                <input
                  type="date" min={todayIso}
                  value={settingsForm.start_date}
                  onChange={(e) => setSettingsForm((f) => ({ ...f, start_date: e.target.value }))}
                  style={{ ...inputStyle, fontSize: 12, padding: "4px 6px", marginTop: 2 }}
                />
              </label>
            )}
            {t.duration_days != null && (
              <input
                type="number" min={1}
                value={settingsForm.duration_days}
                onChange={(e) => setSettingsForm((f) => ({ ...f, duration_days: e.target.value }))}
                placeholder="Длительность (дней)"
                style={{ ...inputStyle, fontSize: 12, padding: "4px 6px" }}
              />
            )}
            <input
              value={settingsForm.hashtag}
              onChange={(e) => setSettingsForm((f) => ({ ...f, hashtag: e.target.value }))}
              placeholder="Хэштег для результата (например #вордли)"
              style={{ ...inputStyle, fontSize: 12, padding: "4px 6px" }}
            />
            <textarea
              value={settingsForm.note}
              onChange={(e) => setSettingsForm((f) => ({ ...f, note: e.target.value }))}
              placeholder="Заметка админа (описание, игрокам не видна)"
              style={{ ...inputStyle, fontSize: 12, padding: "4px 6px", minHeight: 44, resize: "vertical" }}
            />
            <div style={{ display: "flex", gap: 4 }}>
              <button onClick={() => handleSaveSettings(t)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
              <button onClick={() => setEditingSettings(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
            {t.status !== "active" && (
              <button
                onClick={(e) => { e.stopPropagation(); handleActivate(t.id); }}
                style={{ ...ghostButtonStyle, fontSize: 12 }}
              >
                Активировать
              </button>
            )}
            {(t.status === "active" || t.status === "tiebreak" || t.status === "playoff") && (
              <button
                onClick={(e) => { e.stopPropagation(); handleTogglePause(t); }}
                title="Немедленно блокирует игру для всех участников без изменения статуса розыгрыша"
                style={{ ...ghostButtonStyle, fontSize: 12 }}
              >
                {t.paused ? "Возобновить" : "Приостановить"}
              </button>
            )}
            {(t.archived || t.status === "finished" || t.paused) && (
              <button
                onClick={(e) => { e.stopPropagation(); handleToggleArchived(t); }}
                title="Убрать розыгрыш с глаз долой в архив (или вернуть обратно)"
                style={{ ...ghostButtonStyle, fontSize: 12 }}
              >
                {t.archived ? "Вернуть из архива" : "В архив"}
              </button>
            )}
            <button
              onClick={(e) => { e.stopPropagation(); startEditSettings(t); }}
              style={{ ...ghostButtonStyle, fontSize: 12 }}
            >
              Настройки
            </button>
          </div>
        )}
      </div>
    );
  }

  const liveTournaments = tournaments.filter((t) => !t.archived);
  const archivedTournaments = tournaments.filter((t) => t.archived);
  const archivedByYear = {};
  for (const t of archivedTournaments) {
    const year = t.start_date ? t.start_date.slice(0, 4) : "—";
    (archivedByYear[year] ||= []).push(t);
  }
  const archivedYears = Object.keys(archivedByYear).sort((a, b) => b.localeCompare(a));

  return (
    <div style={panelStyle}>
      <h3 style={{ marginTop: 0 }}>Розыгрыши</h3>
      {liveTournaments.map(renderCard)}

      {archivedTournaments.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <button
            onClick={() => setShowArchive((v) => !v)}
            style={{ ...ghostButtonStyle, fontSize: 13, width: "100%" }}
          >
            {showArchive ? "▾" : "▸"} Архив ({archivedTournaments.length})
          </button>
          {showArchive && archivedYears.map((year) => (
            <div key={year} style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 4 }}>{year}</div>
              {archivedByYear[year].map(renderCard)}
            </div>
          ))}
        </div>
      )}

      {!showForm ? (
        <button onClick={() => setShowForm(true)} style={buttonStyle}>+ Новый розыгрыш</button>
      ) : (
        <form onSubmit={handleCreate} style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
          <input
            placeholder="Название (день/стадия добавляются автоматически)"
            value={title} onChange={(e) => setTitle(e.target.value)} style={inputStyle} required
          />
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
          <input placeholder="Хэштег для результата (например #вордли), опционально" value={hashtag} onChange={(e) => setHashtag(e.target.value)} style={inputStyle} />
          <textarea
            placeholder="Заметка админа (описание, игрокам не видна), опционально"
            value={note} onChange={(e) => setNote(e.target.value)} style={{ ...inputStyle, minHeight: 50, resize: "vertical" }}
          />
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
  const [hideFromStandings, setHideFromStandings] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    setEntries(await api(`/api/admin/tournaments/${tournament.id}/entries`));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  const connectedUserIds = new Set(entries.filter((e) => e.active).map((e) => e.user_id));
  const availableUsers = users.filter((u) => !connectedUserIds.has(u.id) && !u.archived);
  const activeCount = entries.filter((e) => e.active).length;
  const inactiveCount = entries.length - activeCount;

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/entries`, {
        method: "POST",
        body: JSON.stringify({ user_id: Number(userId), callsign, hidden_from_standings: hideFromStandings }),
      });
      setUserId("");
      setCallsign("");
      setHideFromStandings(false);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function toggleActive(entry) {
    if (entry.active && !window.confirm(`Отключить «${entry.callsign}» от розыгрыша? Набранная статистика останется в таблице.`)) {
      return;
    }
    await api(`/api/admin/entries/${entry.id}/active`, {
      method: "PATCH",
      body: JSON.stringify({ active: !entry.active }),
    });
    refresh();
  }

  async function toggleHidden(entry) {
    await api(`/api/admin/entries/${entry.id}/hidden`, {
      method: "PATCH",
      body: JSON.stringify({ hidden_from_standings: !entry.hidden_from_standings }),
    });
    refresh();
  }

  return (
    <div style={panelStyle}>
      <h3 style={{ marginTop: 0 }}>Участники «{tournament.title}»</h3>
      <p style={{ opacity: 0.7, fontSize: 13, marginTop: -4 }}>
        Подключено: {activeCount}{inactiveCount > 0 ? ` · Отключено: ${inactiveCount}` : ""}
      </p>
      <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <select value={userId} onChange={(e) => setUserId(e.target.value)} style={inputStyle} required>
          <option value="" disabled>Выберите игрока</option>
          {availableUsers.map((u) => (
            <option key={u.id} value={u.id}>{u.admin_note || `Игрок #${u.id}`}</option>
          ))}
        </select>
        <input placeholder="Позывной для этого розыгрыша" value={callsign} onChange={(e) => setCallsign(e.target.value)} style={inputStyle} required />
        {tournament.type !== "knockout" && (
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, opacity: 0.8, cursor: "pointer" }}>
            <input type="checkbox" checked={hideFromStandings} onChange={(e) => setHideFromStandings(e.target.checked)} />
            не учитывать в таблице
          </label>
        )}
        <button type="submit" style={buttonStyle}>Подключить</button>
      </form>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left", opacity: 0.7, fontSize: 13 }}>
            <th style={thStyle}>Позывной</th>
            <th style={thStyle}>Игрок</th>
            <th style={thStyle}>Статус</th>
            <th style={thStyle}></th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const u = users.find((x) => x.id === e.user_id);
            return (
              <tr key={e.id} style={{ borderTop: "1px solid #2a2a2c", opacity: e.active ? 1 : 0.5 }}>
                <td style={tdStyle}>{e.callsign}</td>
                <td style={{ ...tdStyle, opacity: 0.7 }}>{u?.admin_note || `Игрок #${e.user_id}`}</td>
                <td style={tdStyle}>
                  {e.active ? "Подключён" : "Отключён"}
                  {tournament.type !== "knockout" && e.hidden_from_standings && (
                    <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.6, border: "1px solid #3a3a3c", borderRadius: 4, padding: "1px 5px" }}>
                      не в таблице
                    </span>
                  )}
                </td>
                <td style={tdStyle}>
                  <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    <button onClick={() => toggleActive(e)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                      {e.active ? "Отключить" : "Подключить"}
                    </button>
                    {tournament.type !== "knockout" && (
                      <button onClick={() => toggleHidden(e)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                        {e.hidden_from_standings ? "Учитывать в таблице" : "Не учитывать в таблице"}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function TodayWordPanel({ tournament }) {
  const [word, setWord] = useState(null);
  const [notApplicable, setNotApplicable] = useState(false);
  const [excluded, setExcluded] = useState(false);
  const [yesterday, setYesterday] = useState(null);

  async function refresh() {
    try {
      const data = await api(`/api/admin/tournaments/${tournament.id}/words/today`);
      setWord(data);
      setExcluded(false);
      setNotApplicable(false);
      // В бессрочной игре дополнительно показываем вчерашнее слово прямо тут —
      // у неё нет фиксированного диапазона дней, чтобы держать это в истории
      // "по умолчанию" (см. пункт бэклога: вчера/сегодня/завтра).
      if (tournament.type === "endless" && data.day_number > 1) {
        const history = await api(`/api/admin/tournaments/${tournament.id}/words`);
        setYesterday(history.find((w) => w.day_number === data.day_number - 1) || null);
      } else {
        setYesterday(null);
      }
    } catch (e) {
      setNotApplicable(true);
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

  if (notApplicable || !word) return null;

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <h3 style={{ marginTop: 0 }}>Слово сегодня — день {word.day_number} ({word.calendar_date})</h3>
      <p style={{ fontSize: 13, opacity: 0.7, marginTop: -4 }}>
        День уже идёт, менять слово поздно — это просто справка для админа.
      </p>
      {yesterday && (
        <div style={{ fontSize: 13, opacity: 0.6, marginBottom: 8 }}>
          Вчера (день {yesterday.day_number}): <b style={{ textTransform: "uppercase", letterSpacing: 1 }}>{yesterday.word}</b>
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 22, fontWeight: 700, textTransform: "uppercase", letterSpacing: 2 }}>{word.word}</span>
        <button
          onClick={handleExclude}
          disabled={excluded}
          title="Больше не предлагать это слово в будущем — на сегодняшнее слово не влияет"
          style={{ ...ghostButtonStyle, fontSize: 12 }}
        >
          {excluded ? "Исключено из будущих слов" : "🚫 Исключить из словаря"}
        </button>
      </div>
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

  async function handleExcludeAndReroll() {
    setError("");
    try {
      await api("/api/admin/dictionary/excluded", { method: "POST", body: JSON.stringify({ word: word.word }) });
      await handleReroll();
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
        <button
          onClick={handleExcludeAndReroll}
          title="Исключить это слово из будущих предложений и сразу показать другое"
          style={ghostButtonStyle}
        >
          🚫 Исключить и предложить другое
        </button>
        <input placeholder="Или ввести своё слово" value={override} onChange={(e) => setOverride(e.target.value)} style={inputStyle} maxLength={5} />
        <button onClick={() => handleConfirm(true)} disabled={override.trim().length !== 5} style={ghostButtonStyle}>Заменить</button>
      </div>
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}

function WordHistoryPanel({ tournament }) {
  const [words, setWords] = useState(null);
  const [open, setOpen] = useState(false);

  async function refresh() {
    setWords(await api(`/api/admin/tournaments/${tournament.id}/words`));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  if (!words) return null;
  const sorted = [...words].sort((a, b) => b.day_number - a.day_number);

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        <h3 style={{ margin: 0 }}>История слов {open ? "▾" : "▸"}</h3>
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
            {sorted.map((w) => (
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

function StandingsPanel({ tournament }) {
  const [standings, setStandings] = useState(null);
  const [editing, setEditing] = useState(null); // {participantId, day} | null
  const [form, setForm] = useState({ attempts_used: 1, solved: true, note: "" });
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [hoveredCell, setHoveredCell] = useState(null); // {participantId, day} | null

  async function handleCopyStandings() {
    const tags = [standings.hashtag, "#таблица", `#день${standings.current_day}`].filter(Boolean).join(" ");
    const lines = standings.rows.map((r) => `${r.place}. ${r.callsign} — ${r.total_points}`);
    const text = `${tags}\n\n${lines.join("\n")}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      setCopied(false);
    }
  }

  function handleDownloadStandings() {
    const dpr = window.devicePixelRatio || 1;
    const dayCol = 34;
    const placeCol = 34;
    const totalCol = 54;
    const font = "14px system-ui, sans-serif";
    const measureCanvas = document.createElement("canvas");
    const mctx = measureCanvas.getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const callsignCol = Math.max(90, ...standings.rows.map((r) => mctx.measureText(r.callsign).width + 20));

    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const tableWidth = placeCol + callsignCol + totalCol + dayCol * standings.total_days;
    const width = tableWidth + padding * 2;
    const height = headerHeight + rowHeight * standings.rows.length + padding * 2;

    const canvas = document.createElement("canvas");
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.textBaseline = "middle";

    const tableTop = padding;
    let x = padding;
    const colX = { place: x };
    x += placeCol;
    colX.callsign = x;
    x += callsignCol;
    colX.total = x;
    x += totalCol;
    const dayX = [];
    for (let i = 0; i < standings.total_days; i++) {
      dayX.push(x);
      x += dayCol;
    }

    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, tableTop, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("#", colX.place + placeCol / 2, tableTop + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Позывной", colX.callsign + 6, tableTop + headerHeight / 2);
    ctx.textAlign = "center";
    ctx.fillText("Σ", colX.total + totalCol / 2, tableTop + headerHeight / 2);
    for (let i = 0; i < standings.total_days; i++) {
      ctx.fillText(`${i + 1}`, dayX[i] + dayCol / 2, tableTop + headerHeight / 2);
    }

    standings.rows.forEach((r, ri) => {
      const rowY = tableTop + headerHeight + ri * rowHeight;
      if (ri % 2 === 1) {
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(padding, rowY, tableWidth, rowHeight);
      }
      ctx.fillStyle = "#1a1a1b";
      ctx.font = font;
      ctx.textAlign = "center";
      ctx.fillText(String(r.place), colX.place + placeCol / 2, rowY + rowHeight / 2);
      ctx.textAlign = "left";
      ctx.fillText(r.callsign, colX.callsign + 6, rowY + rowHeight / 2);
      ctx.textAlign = "center";
      ctx.font = "bold " + font;
      ctx.fillText(String(r.total_points), colX.total + totalCol / 2, rowY + rowHeight / 2);
      ctx.font = font;
      r.daily.forEach((d, di) => {
        const label = d.played ? String(d.points) : (d.not_played_yet ? "—" : standings.skip_flag_symbol);
        ctx.fillStyle = d.played ? "#1a1a1b" : "#999";
        ctx.fillText(label, dayX[di] + dayCol / 2, rowY + rowHeight / 2);
      });
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let ri = 0; ri <= standings.rows.length; ri++) {
      const y = tableTop + headerHeight + ri * rowHeight;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(padding + tableWidth, y);
      ctx.stroke();
    }

    canvas.toBlob((blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${tournament.title.replace(/[^\p{L}\p{N}]+/gu, "_")}.png`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  async function refresh() {
    setStandings(await api(`/api/admin/tournaments/${tournament.id}/standings`));
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  if (!standings) return null;

  function startEdit(participantId, day, cell) {
    setError("");
    setEditing({ participantId, day });
    setForm({
      attempts_used: cell.played ? 1 : 1,
      solved: cell.played ? cell.points > 0 : true,
      note: "",
    });
  }

  async function handleSave() {
    setError("");
    try {
      await api(`/api/admin/entries/${editing.participantId}/days/${editing.day}/override`, {
        method: "POST",
        body: JSON.stringify({
          attempts_used: Number(form.attempts_used),
          solved: form.solved,
          note: form.note,
        }),
      });
      setEditing(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div style={{ ...panelStyle, marginTop: 20, overflowX: "auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ marginTop: 0 }}>Таблица</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleCopyStandings} style={ghostButtonStyle}>
            {copied ? "Скопировано!" : "Скопировать таблицу"}
          </button>
          <button onClick={handleDownloadStandings} style={ghostButtonStyle}>Скачать таблицу</button>
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      <p style={{ fontSize: 12, opacity: 0.6, marginTop: -4 }}>
        Клик по ячейке дня — ручная корректировка результата (исключительные случаи). Наведите на цифру — покажутся попытки этого дня.
      </p>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}
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
              {r.daily.map((d, i) => {
                const day = i + 1;
                const isEditing = editing?.participantId === r.participant_id && editing?.day === day;
                if (isEditing) {
                  return (
                    <td key={i} style={{ ...tdStyle, background: "#2a2a2c" }}>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 140 }}>
                        <input
                          type="number" min={1} max={6} value={form.attempts_used}
                          onChange={(e) => setForm((f) => ({ ...f, attempts_used: e.target.value }))}
                          style={{ ...inputStyle, padding: "2px 6px", fontSize: 12 }}
                          placeholder="Попыток"
                        />
                        <label style={{ fontSize: 11, display: "flex", gap: 4, alignItems: "center" }}>
                          <input
                            type="checkbox" checked={form.solved}
                            onChange={(e) => setForm((f) => ({ ...f, solved: e.target.checked }))}
                          />
                          угадал
                        </label>
                        <input
                          placeholder="Причина (обязательно)" value={form.note}
                          onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                          style={{ ...inputStyle, padding: "2px 6px", fontSize: 12 }}
                        />
                        <div style={{ display: "flex", gap: 4 }}>
                          <button onClick={handleSave} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
                          <button onClick={() => setEditing(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
                        </div>
                      </div>
                    </td>
                  );
                }
                const isHovered = hoveredCell?.participantId === r.participant_id && hoveredCell?.day === day;
                return (
                  <td
                    key={i}
                    onClick={() => startEdit(r.participant_id, day, d)}
                    onMouseEnter={() => { if (d.guesses?.length > 0) setHoveredCell({ participantId: r.participant_id, day }); }}
                    onMouseLeave={() => setHoveredCell(null)}
                    title={d.admin_note ? `Скорректировано: ${d.admin_note}` : "Клик — скорректировать"}
                    style={{ ...tdStyle, textAlign: "center", cursor: "pointer", position: "relative" }}
                  >
                    {d.played ? d.points : (d.not_played_yet ? "—" : standings.skip_flag_symbol)}
                    {d.admin_note && <sup style={{ color: "#e5a94c" }}>✎</sup>}
                    {isHovered && (
                      <div
                        style={{
                          position: "absolute", bottom: "100%", left: "50%", transform: "translateX(-50%)",
                          background: "#1c1c1e", border: "1px solid #3a3a3c", borderRadius: 6, padding: "6px 10px",
                          whiteSpace: "nowrap", zIndex: 10, marginBottom: 4, textAlign: "left", pointerEvents: "none",
                        }}
                      >
                        {d.guesses.map((g, gi) => (
                          <div key={gi} style={{ fontFamily: "monospace", fontSize: 13, letterSpacing: 1, textTransform: "uppercase" }}>
                            {g}
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                );
              })}
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
  const [overridingRoundId, setOverridingRoundId] = useState(null);
  const [ranks, setRanks] = useState({});
  const [orderNote, setOrderNote] = useState("");

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

  function startOverride(round) {
    setError("");
    setOverridingRoundId(round.id);
    const initial = {};
    round.participants.forEach((p, i) => { initial[p.entry_id] = i + 1; });
    setRanks(initial);
    setOrderNote("");
  }

  async function handleSubmitOrder(round) {
    setError("");
    try {
      const order = [...round.participants]
        .sort((a, b) => (Number(ranks[a.entry_id]) || 0) - (Number(ranks[b.entry_id]) || 0))
        .map((p) => p.entry_id);
      await api(`/api/admin/tiebreak/rounds/${round.id}/override`, {
        method: "POST",
        body: JSON.stringify({ order, note: orderNote }),
      });
      setOverridingRoundId(null);
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
            {r.manual_order && (
              <span title={`Скорректировано: ${r.admin_note}`} style={{ color: "#e5a94c" }}> ✎ порядок задан вручную</span>
            )}
          </div>
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {r.participants.map((p) => (
                <tr key={p.entry_id}>
                  <td style={tdStyle}>{p.callsign}</td>
                  <td style={tdStyle}>
                    {p.attempts_used == null ? "ещё не играл" : `${p.solved ? "угадал" : "не угадал"} за ${p.attempts_used}`}
                  </td>
                  {overridingRoundId === r.id && (
                    <td style={tdStyle}>
                      <input
                        type="number" min={1} value={ranks[p.entry_id] || ""}
                        onChange={(e) => setRanks((prev) => ({ ...prev, [p.entry_id]: e.target.value }))}
                        style={{ ...inputStyle, width: 50, padding: "2px 6px", fontSize: 12 }}
                        placeholder="Место"
                      />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {overridingRoundId === r.id ? (
            <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
              <input
                placeholder="Причина (обязательно)" value={orderNote}
                onChange={(e) => setOrderNote(e.target.value)}
                style={{ ...inputStyle, padding: "4px 8px", fontSize: 12, flex: 1 }}
              />
              <button
                onClick={() => handleSubmitOrder(r)}
                disabled={!orderNote.trim()}
                style={{ ...buttonStyle, padding: "4px 10px", fontSize: 12 }}
              >
                Сохранить порядок
              </button>
              <button onClick={() => setOverridingRoundId(null)} style={{ ...ghostButtonStyle, padding: "4px 10px", fontSize: 12 }}>Отмена</button>
            </div>
          ) : (
            <button onClick={() => startOverride(r)} style={{ ...ghostButtonStyle, padding: "4px 10px", fontSize: 12, marginTop: 8 }}>
              Задать порядок вручную
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

const MATCH_STATUS_LABEL = { pending: "ожидает", in_progress: "идёт", finished: "завершён" };

function formatAttempts(attemptsUsed, solved) {
  if (attemptsUsed == null) return "";
  return `(${solved ? attemptsUsed : "X"}/6)`;
}

function MatchWordQueue({ matchId }) {
  const [queue, setQueue] = useState(null);
  const [editingNum, setEditingNum] = useState(null);
  const [wordForm, setWordForm] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setQueue(await api(`/api/admin/bracket/matches/${matchId}/words`));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchId]);

  async function handleSet(gameNumber) {
    setError("");
    try {
      await api(`/api/admin/bracket/matches/${matchId}/words/${gameNumber}`, {
        method: "POST",
        body: JSON.stringify({ word: wordForm.trim().toLowerCase() }),
      });
      setEditingNum(null);
      setWordForm("");
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
        Очередь слов — 1: текущее, 2-3: превью на случай ничьей. С 4-й игры слова генерируются автоматически.
      </div>
      {error && <div style={{ color: "#e5484d", fontSize: 11, marginBottom: 4 }}>{error}</div>}
      {queue.map((q) => (
        <div key={q.game_number} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
          <span style={{ fontSize: 11, opacity: 0.6, width: 55 }}>Игра {q.game_number}:</span>
          {editingNum === q.game_number ? (
            <>
              <input
                autoFocus value={wordForm} onChange={(e) => setWordForm(e.target.value)} maxLength={5}
                style={{ ...inputStyle, padding: "2px 6px", fontSize: 12, width: 80 }}
              />
              <button onClick={() => handleSet(q.game_number)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
              <button onClick={() => setEditingNum(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
            </>
          ) : (
            <>
              <span style={{ textTransform: "uppercase", letterSpacing: 1, fontSize: 13 }}>{q.word}</span>
              {q.editable && (
                <>
                  <button
                    onClick={() => { setEditingNum(q.game_number); setWordForm(q.word); }}
                    style={{ ...ghostButtonStyle, padding: "1px 6px", fontSize: 11 }}
                  >
                    Заменить
                  </button>
                  <button
                    onClick={() => handleReroll(q.game_number)}
                    style={{ ...ghostButtonStyle, padding: "1px 6px", fontSize: 11 }}
                  >
                    Предложить другое
                  </button>
                </>
              )}
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function BracketPanel({ tournament }) {
  const [entries, setEntries] = useState([]);
  const [matches, setMatches] = useState(null);
  const [pairSelections, setPairSelections] = useState([]);
  const [error, setError] = useState("");
  const [overriding, setOverriding] = useState(null); // matchId | null
  const [overrideNote, setOverrideNote] = useState("");
  const [wordQueueOpenId, setWordQueueOpenId] = useState(null); // matchId | null

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
                return (
                <Fragment key={m.id}>
                <tr style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={tdStyle}>
                    Р{m.round_number} · пара {m.position + 1}
                    {m.is_sudden_death && <span style={{ opacity: 0.6 }}> (доп. раунд)</span>}
                    {m.word && (
                      <div style={{ opacity: 0.6, fontSize: 11, textTransform: "uppercase" }}>слово: {m.word}</div>
                    )}
                  </td>
                  <td style={tdStyle}>{m.entry_a_callsign || "— пусто —"} {formatAttempts(m.entry_a_attempts_used, m.entry_a_solved)}</td>
                  <td style={tdStyle}>—</td>
                  <td style={tdStyle}>{m.entry_b_callsign || "— пусто —"} {formatAttempts(m.entry_b_attempts_used, m.entry_b_solved)}</td>
                  <td style={{ ...tdStyle, opacity: 0.7 }}>
                    {m.winner_entry_id
                      ? <>победил: {m.winner_entry_id === m.entry_a_id ? m.entry_a_callsign : m.entry_b_callsign}
                        {m.admin_note && <sup title={`Скорректировано: ${m.admin_note}`} style={{ color: "#e5a94c" }}> ✎</sup>}</>
                      : (m.status === "finished" ? "пустая пара" : MATCH_STATUS_LABEL[m.status] || m.status)}
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {hasBothSides && m.status !== "finished" && (
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
                      <MatchWordQueue matchId={m.id} />
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
                {slots.map((m, i) => {
                  const y = centers[rIdx][i] - BOX_H / 2;
                  const nameA = m?.entry_a_callsign || "?";
                  const nameB = m?.entry_b_callsign || "?";
                  const winnerA = m?.winner_entry_id != null && m.winner_entry_id === m.entry_a_id;
                  const winnerB = m?.winner_entry_id != null && m.winner_entry_id === m.entry_b_id;
                  const attemptsA = formatAttempts(m?.entry_a_attempts_used, m?.entry_a_solved);
                  const attemptsB = formatAttempts(m?.entry_b_attempts_used, m?.entry_b_solved);
                  return (
                    <g key={`box-${rIdx}-${i}`}>
                      <rect x={x} y={y} width={BOX_W} height={BOX_H} rx={6} fill={i % 2 === 1 ? "#fafafa" : "#ffffff"} stroke="#ddd" />
                      <line x1={x} y1={y + BOX_H / 2} x2={x + BOX_W} y2={y + BOX_H / 2} stroke="#ddd" />
                      <text x={x + 8} y={y + BOX_H / 2 - 6} fontSize="13" fill={winnerA ? "#6aaa64" : "#1a1a1b"} fontWeight={winnerA ? "700" : "400"}>
                        {nameA}
                      </text>
                      <text x={x + BOX_W - 8} y={y + BOX_H / 2 - 6} fontSize="11" textAnchor="end" fill={winnerA ? "#6aaa64" : "#999"}>
                        {attemptsA}
                      </text>
                      <text x={x + 8} y={y + BOX_H - 6} fontSize="13" fill={winnerB ? "#6aaa64" : "#1a1a1b"} fontWeight={winnerB ? "700" : "400"}>
                        {nameB}
                      </text>
                      <text x={x + BOX_W - 8} y={y + BOX_H - 6} fontSize="11" textAnchor="end" fill={winnerB ? "#6aaa64" : "#999"}>
                        {attemptsB}
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

function Centered({ children }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#121213", color: "#fff" }}>
      {children}
    </div>
  );
}

const panelStyle = { background: "#1c1c1e", borderRadius: 10, padding: 16 };
// colorScheme: "dark" — иначе нативная иконка календаря/цвета у <input type="date">
// рисуется тёмной по умолчанию и сливается с тёмным фоном поля (см. пункт бэклога).
const inputStyle = { padding: "8px 10px", borderRadius: 6, border: "1px solid #3a3a3c", background: "#121213", color: "#fff", fontSize: 14, colorScheme: "dark" };
const buttonStyle = { padding: "8px 12px", borderRadius: 6, border: "none", background: "#538d4e", color: "#fff", fontSize: 14, cursor: "pointer" };
const ghostButtonStyle = { padding: "6px 10px", borderRadius: 6, border: "1px solid #3a3a3c", background: "transparent", color: "#fff", fontSize: 13, cursor: "pointer" };
const thStyle = { padding: "4px 8px", textAlign: "left" };
const tdStyle = { padding: "4px 8px" };
