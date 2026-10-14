import { Fragment, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ADMIN_BASE } from "../adminBase.js";
import HallView from "../components/HallView.jsx";

function useIsMobile(breakpoint = 640) {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < breakpoint);
  useEffect(() => {
    function onResize() {
      setIsMobile(window.innerWidth < breakpoint);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);
  return isMobile;
}

// Всегда актуальное значение для отбрасывания устаревших ответов — если
// админ успел переключиться на другой розыгрыш/матч, пока запрос летал,
// применять его результат уже нельзя (иначе на экране повиснут данные не
// того розыгрыша под правильным заголовком). См. refresh() в панелях ниже.
function useLatest(value) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

const DEFAULT_SCORING = { "1": 10, "2": 5, "3": 4, "4": 3, "5": 2, "6": 1 };
const TYPE_LABEL = { standard: "Стандартный", knockout: "На вылет", championship: "Чемпионат", endless: "Бессрочная игра", tiebreak: "Тай-брейк" };
const STATUS_LABEL = { draft: "черновик", active: "идёт", tiebreak: "тай-брейк", playoff: "плей-офф", finished: "завершён" };

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    window.location.href = ADMIN_BASE;
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
  const isMobile = useIsMobile();
  const [tab, setTab] = useState("tournaments");
  const [tournaments, setTournaments] = useState([]);
  const [users, setUsers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState("dark");

  async function refreshTournaments() {
    const data = await api("/api/admin/tournaments");
    setTournaments(data);
    // По умолчанию — первый неархивный розыгрыш, а не просто первый в списке
    // (иначе при первой загрузке могло открыться меню архивного розыгрыша,
    // если он оказался раньше в ответе API).
    const firstLive = data.find((t) => !t.archived) || data[0] || null;
    setSelected((prev) => (prev ? data.find((t) => t.id === prev.id) || firstLive : firstLive));
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
    navigate(ADMIN_BASE);
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
          <TabButton active={tab === "hall"} onClick={() => setTab("hall")}>Зал славы</TabButton>
        </div>
      </div>

      <div style={{ padding: 20 }}>
      {tab === "users" && <UsersPanel users={users} onChanged={refreshUsers} />}
      {tab === "dictionary" && <DictionaryPanel />}
      {tab === "hall" && <HallPanel users={users} />}

      {tab === "tournaments" && (
        <div style={isMobile ? { display: "flex", flexDirection: "column", gap: 24 } : { display: "flex", gap: 24, flexWrap: "wrap" }}>
          <div style={isMobile ? {} : { flex: "1 1 300px" }}>
            <TournamentPanel
              tournaments={tournaments}
              selected={selected}
              onSelect={setSelected}
              onCreated={refreshTournaments}
              onActivated={refreshTournaments}
            />
          </div>
          <div style={isMobile ? {} : { flex: "2 1 500px" }}>
            {selected ? (
              <>
                <EntriesPanel tournament={selected} users={users} allTournaments={tournaments} />
                {selected.type === "tiebreak" && <TiebreakWordsPanel tournament={selected} />}
                {selected.type !== "knockout" && selected.type !== "tiebreak" && <TodayWordPanel tournament={selected} />}
                {selected.type !== "knockout" && selected.type !== "tiebreak" && <WordConfirmPanel tournament={selected} />}
                {selected.type !== "knockout" && selected.type !== "tiebreak" && <WordHistoryPanel tournament={selected} />}
                {selected.type === "tiebreak" && <TiebreakResultsPanel tournament={selected} />}
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
  const isMobile = useIsMobile();
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState(null);
  const [showArchived, setShowArchived] = useState(false);
  const [editingNoteId, setEditingNoteId] = useState(null);
  const [noteForm, setNoteForm] = useState("");
  const [openMenuId, setOpenMenuId] = useState(null);
  const [expandedToursIds, setExpandedToursIds] = useState(() => new Set());
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

  function renderCard(u) {
    const isEditingNote = editingNoteId === u.id;
    const isMenuOpen = openMenuId === u.id;
    const toursExpanded = expandedToursIds.has(u.id);

    function runAction(fn) {
      setOpenMenuId(null);
      fn(u);
    }

    return (
      <div key={u.id} style={{ background: "#1c1c1e", borderRadius: 10, padding: 12, marginBottom: 8, position: "relative", zIndex: isMenuOpen ? 3 : "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
          {isEditingNote ? (
            <div style={{ display: "flex", gap: 4, flex: 1 }}>
              <input
                autoFocus
                value={noteForm}
                onChange={(e) => setNoteForm(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") saveNote(u); if (e.key === "Escape") setEditingNoteId(null); }}
                style={{ ...inputStyle, padding: "2px 6px", fontSize: 13, flex: 1 }}
              />
              <button onClick={() => saveNote(u)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
              <button onClick={() => setEditingNoteId(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
            </div>
          ) : (
            <div style={{ fontSize: 14, fontWeight: 500 }}>
              {u.admin_note || `Игрок #${u.id}`}
              <button
                onClick={() => { setEditingNoteId(u.id); setNoteForm(u.admin_note || ""); }}
                title="Изменить заметку"
                style={{ ...ghostButtonStyle, marginLeft: 6, padding: "0px 6px", fontSize: 11 }}
              >
                ✎
              </button>
            </div>
          )}
          {!isEditingNote && !u.archived && (
            <div style={{ position: "relative", flexShrink: 0 }}>
              <button
                onClick={() => setOpenMenuId(isMenuOpen ? null : u.id)}
                title="Действия"
                style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #3a3a3c", background: "transparent", color: "#818384", fontSize: 16, cursor: "pointer" }}
              >
                ⋮
              </button>
              {isMenuOpen && (
                <div style={{ position: "absolute", right: 0, top: 32, background: "#242426", border: "1px solid #3a3a3c", borderRadius: 8, padding: 4, minWidth: 150, zIndex: 2 }}>
                  <button
                    onClick={() => runAction(handleRegenerateLink)}
                    style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 10px", background: "transparent", border: "none", color: "#e0e0e0", fontSize: 13, cursor: "pointer", borderRadius: 6 }}
                  >
                    Новая ссылка
                  </button>
                  <button
                    onClick={() => runAction(handleDisconnect)}
                    style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 10px", background: "transparent", border: "none", color: "#e0e0e0", fontSize: 13, cursor: "pointer", borderRadius: 6 }}
                  >
                    Отключить
                  </button>
                  <button
                    onClick={() => runAction(handleArchive)}
                    style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 10px", background: "transparent", border: "none", color: "#e0e0e0", fontSize: 13, cursor: "pointer", borderRadius: 6 }}
                  >
                    В архив
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ fontSize: 12, marginTop: 6 }}>
          {u.tournaments.length === 0 ? (
            <span style={{ opacity: 0.5 }}>—</span>
          ) : u.tournaments.length <= 2 || toursExpanded ? (
            u.tournaments.map((t, i) => (
              <span key={t.tournament_id}>
                {i > 0 && ", "}
                <span style={{ opacity: t.active ? 1 : 0.5 }}>
                  {t.title}{!t.active && " (отключён)"}
                </span>
              </span>
            ))
          ) : (
            <span
              onClick={() => setExpandedToursIds((prev) => new Set(prev).add(u.id))}
              style={{ opacity: 0.7, cursor: "pointer" }}
            >
              {u.tournaments.length} розыгрышей ▾
            </span>
          )}
        </div>

        <div style={{ marginTop: 10 }}>
          {u.archived ? (
            <button onClick={() => handleRestore(u)} style={{ ...ghostButtonStyle, width: "100%" }}>
              Восстановить
            </button>
          ) : (
            <button onClick={() => copyLink(u)} style={{ ...ghostButtonStyle, width: "100%" }}>
              {copiedId === u.id ? "Скопировано!" : "Копировать ссылку"}
            </button>
          )}
        </div>
      </div>
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

      {isMobile ? (
        <>
          {openMenuId != null && (
            <div onClick={() => setOpenMenuId(null)} style={{ position: "fixed", inset: 0, zIndex: 1 }} />
          )}
          <div>{activeUsers.map(renderCard)}</div>
        </>
      ) : (
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
      )}
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
            isMobile ? (
              <div style={{ marginTop: 8 }}>{archivedUsers.map(renderCard)}</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8 }}>
                <tbody>{archivedUsers.map(renderRow)}</tbody>
              </table>
            )
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

  const [addedWords, setAddedWords] = useState([]);
  const [newAddedWord, setNewAddedWord] = useState("");
  const [addedError, setAddedError] = useState("");

  async function refresh() {
    setWords(await api("/api/admin/dictionary/excluded"));
  }

  async function refreshAdded() {
    setAddedWords(await api("/api/admin/dictionary/added"));
  }

  useEffect(() => {
    refresh();
    refreshAdded();
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

  async function handleAddMissing(e) {
    e.preventDefault();
    setAddedError("");
    try {
      await api("/api/admin/dictionary/added", {
        method: "POST",
        body: JSON.stringify({ word: newAddedWord.trim().toLowerCase() }),
      });
      setNewAddedWord("");
      refreshAdded();
    } catch (e) {
      setAddedError(e.message);
    }
  }

  async function handleRemoveAdded(id) {
    await api(`/api/admin/dictionary/added/${id}`, { method: "DELETE" });
    refreshAdded();
  }

  return (
    <>
      <div style={{ ...panelStyle, maxWidth: 500, marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Словарь — добавить отсутствующее слово</h3>
        <p style={{ opacity: 0.7, fontSize: 13, marginTop: -4 }}>
          Если игрок ввёл существительное в именительном падеже из 5 букв, а
          игра его не приняла — добавьте его сюда. Сразу становится и валидной
          попыткой, и кандидатом на будущее слово дня, без деплоя.
        </p>
        <form onSubmit={handleAddMissing} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input
            placeholder="Слово из 5 букв"
            value={newAddedWord}
            onChange={(e) => setNewAddedWord(e.target.value)}
            maxLength={20}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button type="submit" style={buttonStyle}>Добавить</button>
        </form>
        {addedError && <div style={{ color: "#e5484d", marginBottom: 8 }}>{addedError}</div>}

        {addedWords.length === 0 ? (
          <div style={{ opacity: 0.5, fontSize: 13 }}>Список пуст.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {addedWords.map((w) => (
                <tr key={w.id} style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={{ ...tdStyle, textTransform: "uppercase", letterSpacing: 1 }}>{w.word}</td>
                  <td style={tdStyle}>
                    <button onClick={() => handleRemoveAdded(w.id)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                      Убрать
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

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
    </>
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
  const [settingsForm, setSettingsForm] = useState({
    title: "", duration_days: "", hashtag: "", note: "", start_date: "", notify_admin: false,
  });
  const [telegramTest, setTelegramTest] = useState(null); // { ok, detail } | null
  const [showArchive, setShowArchive] = useState(false);

  const todayIso = new Date().toISOString().slice(0, 10);

  function startEditSettings(t) {
    setError("");
    setEditingSettings(t.id);
    setSettingsForm({
      title: t.title, duration_days: t.duration_days ?? "", hashtag: t.hashtag || "",
      note: t.note || "", start_date: t.start_date, notify_admin: !!t.notify_admin,
    });
    setTelegramTest(null);
  }

  async function handleTelegramTest() {
    setTelegramTest({ ok: null, detail: "Отправляю..." });
    try {
      setTelegramTest(await api("/api/admin/telegram/test", { method: "POST" }));
    } catch (e) {
      setTelegramTest({ ok: false, detail: e.message });
    }
  }

  async function handleSaveSettings(t) {
    setError("");
    try {
      const body = {
        title: settingsForm.title, hashtag: settingsForm.hashtag, note: settingsForm.note,
        notify_admin: settingsForm.notify_admin,
      };
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
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}>
              <input
                type="checkbox" checked={settingsForm.notify_admin}
                onChange={(e) => setSettingsForm((f) => ({ ...f, notify_admin: e.target.checked }))}
              />
              Уведомлять меня в Telegram, когда игрок закончил партию
            </label>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: 11 }}>
              <button
                type="button" onClick={handleTelegramTest}
                style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}
              >
                Отправить тестовое сообщение
              </button>
              {telegramTest && (
                <span style={{ color: telegramTest.ok === false ? "#e5484d" : telegramTest.ok ? "#538d4e" : undefined, opacity: 0.9 }}>
                  {telegramTest.detail}
                </span>
              )}
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              <button onClick={() => handleSaveSettings(t)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
              <button onClick={() => setEditingSettings(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
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
            <option value="tiebreak">Тай-брейк (распределение мест за один день)</option>
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

function formatClockTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatPlayDuration(startIso, endIso) {
  const totalSeconds = Math.max(0, Math.round((new Date(endIso) - new Date(startIso)) / 1000));
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h} ч ${m} мин`;
  if (m > 0) return `${m} мин`;
  return `${s} сек`;
}

// Текст статуса участника, у которого сегодня уже есть результат: попытки, время
// начала, длительность. У игр без меток времени (сыграны до их появления)
// показываются только попытки.
function playedTodayText(e) {
  const parts = [`${e.played_today_attempts}/6`];
  if (e.played_today_started_at) {
    parts.push(formatClockTime(e.played_today_started_at));
    if (e.played_today_finished_at) parts.push(formatPlayDuration(e.played_today_started_at, e.played_today_finished_at));
  }
  return parts.join(" · ");
}

// Текстовый инпут с крестиком очистки, который появляется, только когда есть
// что очищать (см. пункт бэклога про поиск игрока/позывного).
function ClearableInput({ value, onClear, style, inputStyle: customInputStyle, ...inputProps }) {
  return (
    <div style={{ position: "relative", ...style }}>
      <input
        {...inputProps}
        value={value}
        style={{ ...inputStyle, width: "100%", boxSizing: "border-box", paddingRight: value ? 26 : undefined, ...customInputStyle }}
      />
      {value && (
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={onClear}
          aria-label="Очистить"
          style={{
            position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)",
            background: "transparent", border: "none", color: "var(--muted)", cursor: "pointer",
            fontSize: 16, lineHeight: 1, padding: "2px 4px",
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}

function EntriesPanel({ tournament, users, allTournaments }) {
  const isMobile = useIsMobile();
  const tournamentIdRef = useLatest(tournament.id);
  const [entries, setEntries] = useState([]);
  const [userId, setUserId] = useState("");
  const [userQuery, setUserQuery] = useState("");
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [callsign, setCallsign] = useState("");
  const [hideFromStandings, setHideFromStandings] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [openMenuId, setOpenMenuId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [transferTo, setTransferTo] = useState("");
  const [transferring, setTransferring] = useState(false);
  const [transferMsg, setTransferMsg] = useState(null);
  const [copiedEntryId, setCopiedEntryId] = useState(null);
  const [editingCallsignId, setEditingCallsignId] = useState(null);
  const [callsignForm, setCallsignForm] = useState("");

  async function refresh() {
    const id = tournament.id;
    const data = await api(`/api/admin/tournaments/${id}/entries`);
    if (tournamentIdRef.current === id) setEntries(data);
  }

  useEffect(() => {
    refresh();
    setSelectedIds(new Set());
    setTransferMsg(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  const connectedUserIds = new Set(entries.filter((e) => e.active).map((e) => e.user_id));
  const availableUsers = users.filter((u) => !connectedUserIds.has(u.id) && !u.archived);
  const userQueryLower = userQuery.trim().toLowerCase();
  const matchingUsers = userQueryLower
    ? availableUsers.filter((u) => (u.admin_note || `Игрок #${u.id}`).toLowerCase().includes(userQueryLower))
    : availableUsers;
  const MAX_USER_SUGGESTIONS = 50;
  const shownUsers = matchingUsers.slice(0, MAX_USER_SUGGESTIONS);

  function selectUser(u) {
    setUserId(String(u.id));
    setUserQuery(u.admin_note || `Игрок #${u.id}`);
    setUserMenuOpen(false);
    // По умолчанию — последний позывной, под которым этот игрок участвовал в
    // чём-либо, админ может стереть крестиком (см. пункт бэклога).
    setCallsign(u.last_callsign || "");
  }

  function clearUserSelection() {
    setUserId("");
    setUserQuery("");
    setUserMenuOpen(false);
  }

  const activeCount = entries.filter((e) => e.active).length;
  const inactiveCount = entries.length - activeCount;
  const playedTodayCount = entries.filter((e) => e.active && e.played_today).length;
  // Режимы, где в списке показывается, сыграл ли участник сегодня.
  const tracksToday = ["endless", "standard", "knockout"].includes(tournament.type);
  // Зелёный — уже сыграл, жёлтый — ещё нет; в knockout жёлтым только те, у кого
  // сегодня вообще есть игра (выбывшие/ждущие следующий раунд не подсвечиваются).
  function todayColor(e) {
    if (e.played_today) return "#538d4e";
    if (tournament.type === "knockout" && !e.has_game_today) return undefined;
    return "#e5a94c";
  }
  // Другие неархивные розыгрыши — только в них есть смысл перебрасывать
  // участников (см. пункт бэклога про переброску между розыгрышами).
  const transferTargets = allTournaments.filter((t) => t.id !== tournament.id && !t.archived);

  const query = search.trim().toLowerCase();
  const filteredEntries = entries.filter((e) => {
    if (!query) return true;
    const u = users.find((x) => x.id === e.user_id);
    return e.callsign.toLowerCase().includes(query) || (u?.admin_note || "").toLowerCase().includes(query);
  });
  // Сортировка по умолчанию: сначала те, кто уже сыграл сегодня, затем ещё не
  // сыгравшие, последними — отключённые (см. пункт бэклога). Для режимов без
  // отметки "сегодня" (tracksToday=false) played_today всегда null — первые
  // две группы сливаются в одну, остаётся только деление активен/отключён.
  const entrySortRank = (e) => (!e.active ? 2 : tracksToday && e.played_today ? 0 : 1);
  const sortedEntries = [...filteredEntries].sort((a, b) => {
    const rankDiff = entrySortRank(a) - entrySortRank(b);
    return rankDiff !== 0 ? rankDiff : a.callsign.localeCompare(b.callsign, "ru");
  });
  const selectableVisible = filteredEntries.filter((e) => e.active);
  const allVisibleSelected = selectableVisible.length > 0 && selectableVisible.every((e) => selectedIds.has(e.id));

  function toggleSelect(entryId) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(entryId)) next.delete(entryId);
      else next.add(entryId);
      return next;
    });
  }

  function toggleSelectAllVisible() {
    setSelectedIds((prev) => {
      if (allVisibleSelected) {
        const next = new Set(prev);
        selectableVisible.forEach((e) => next.delete(e.id));
        return next;
      }
      const next = new Set(prev);
      selectableVisible.forEach((e) => next.add(e.id));
      return next;
    });
  }

  async function handleTransfer() {
    const target = transferTargets.find((t) => t.id === Number(transferTo));
    if (!target) return;
    if (!window.confirm(`Перебросить выбранных игроков (${selectedIds.size}) в «${target.title}»? В «${tournament.title}» они будут отключены (статистика останется).`)) {
      return;
    }
    setTransferring(true);
    setTransferMsg(null);
    try {
      const res = await api(`/api/admin/tournaments/${tournament.id}/entries/transfer`, {
        method: "POST",
        body: JSON.stringify({ entry_ids: Array.from(selectedIds), to_tournament_id: target.id }),
      });
      const failed = res.results.filter((r) => !r.ok);
      const okCount = res.results.length - failed.length;
      setTransferMsg(
        failed.length === 0
          ? `Перенесено: ${okCount} из ${res.results.length}.`
          : `Перенесено: ${okCount} из ${res.results.length}. Не удалось: ${failed.map((f) => `«${f.callsign || "?"}» (${f.message})`).join(", ")}`
      );
      setSelectedIds(new Set());
      setTransferTo("");
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setTransferring(false);
    }
  }

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    if (!userId) {
      setError("Выберите игрока из списка");
      return;
    }
    try {
      await api(`/api/admin/tournaments/${tournament.id}/entries`, {
        method: "POST",
        body: JSON.stringify({ user_id: Number(userId), callsign, hidden_from_standings: hideFromStandings }),
      });
      clearUserSelection();
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

  async function saveCallsign(entry) {
    setError("");
    const trimmed = callsignForm.trim();
    if (!trimmed) return;
    try {
      await api(`/api/admin/entries/${entry.id}`, {
        method: "PATCH",
        body: JSON.stringify({ callsign: trimmed }),
      });
      setEditingCallsignId(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  function copyLink(entry) {
    const u = users.find((x) => x.id === entry.user_id);
    if (!u) return;
    navigator.clipboard?.writeText(`${window.location.origin}/play/${u.access_token}`);
    setCopiedEntryId(entry.id);
    setTimeout(() => setCopiedEntryId(null), 1500);
  }

  async function handleResetToday(entry) {
    if (!window.confirm(`Сбросить попытку «${entry.callsign}» за сегодня? Игрок сможет сыграть сегодняшнее слово заново с нуля — введённые буквы и результат за сегодня будут стёрты без возможности отмены.`)) {
      return;
    }
    setError("");
    try {
      await api(`/api/admin/entries/${entry.id}/reset-today`, { method: "POST" });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleDisconnectAll() {
    if (!window.confirm(`Отключить всех подключённых участников (${activeCount}) от «${tournament.title}»? Набранная статистика останется в таблице, подключить обратно можно по одному.`)) {
      return;
    }
    await api(`/api/admin/tournaments/${tournament.id}/entries/disconnect-all`, { method: "POST" });
    refresh();
  }

  async function handleAddAll() {
    if (!window.confirm(`Подключить сразу всех зарегистрированных игроков (${availableUsers.length}) к «${tournament.title}»? Позывные подставятся по умолчанию (заметка админа или «#игрокN») — их можно будет переименовать позже.`)) {
      return;
    }
    await api(`/api/admin/tournaments/${tournament.id}/entries/add-all`, { method: "POST" });
    refresh();
  }

  function renderCard(e) {
    const u = users.find((x) => x.id === e.user_id);
    const isMenuOpen = openMenuId === e.id;
    const isEditingCallsign = editingCallsignId === e.id;

    function runAction(fn) {
      setOpenMenuId(null);
      fn(e);
    }

    return (
      <div key={e.id} style={{ background: "#242426", borderRadius: 10, padding: 12, marginBottom: 8, opacity: e.active ? 1 : 0.5 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
            {e.active && transferTargets.length > 0 && (
              <input
                type="checkbox"
                checked={selectedIds.has(e.id)}
                onChange={() => toggleSelect(e.id)}
                style={{ marginTop: 3 }}
              />
            )}
            <div>
              {isEditingCallsign ? (
                <div style={{ display: "flex", gap: 4 }}>
                  <input
                    autoFocus
                    value={callsignForm}
                    onChange={(ev) => setCallsignForm(ev.target.value)}
                    onKeyDown={(ev) => { if (ev.key === "Enter") saveCallsign(e); if (ev.key === "Escape") setEditingCallsignId(null); }}
                    style={{ ...inputStyle, padding: "2px 6px", fontSize: 13, width: 110 }}
                  />
                  <button onClick={() => saveCallsign(e)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
                  <button onClick={() => setEditingCallsignId(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
                </div>
              ) : (
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  {e.callsign}
                  <button
                    onClick={() => { setEditingCallsignId(e.id); setCallsignForm(e.callsign); }}
                    title="Изменить позывной"
                    style={{ ...ghostButtonStyle, marginLeft: 6, padding: "0px 6px", fontSize: 11 }}
                  >
                    ✎
                  </button>
                </div>
              )}
              <div style={{ fontSize: 12, opacity: 0.7, marginTop: 2 }}>{u?.admin_note || `Игрок #${e.user_id}`}</div>
            </div>
          </div>
          <button
            onClick={() => setOpenMenuId(isMenuOpen ? null : e.id)}
            title="Действия"
            style={{ width: 28, height: 28, borderRadius: 6, border: "1px solid #3a3a3c", background: "transparent", color: "#818384", fontSize: 16, cursor: "pointer", flexShrink: 0 }}
          >
            ⋮
          </button>
        </div>
        {isMenuOpen && (
          // Раскрывается внутри самой карточки (а не плавающим меню поверх) —
          // список участников прокручивается в своей области (см. пункт
          // бэклога), и плавающее меню обрезалось бы этой прокруткой, если
          // карточка ближе к нижнему краю видимой части списка.
          <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8, paddingTop: 8, borderTop: "1px solid #3a3a3c" }}>
            <button onClick={() => copyLink(e)} style={{ ...ghostButtonStyle, textAlign: "left", fontSize: 12 }}>
              {copiedEntryId === e.id ? "Скопировано!" : "Копировать ссылку"}
            </button>
            <button onClick={() => runAction(toggleActive)} style={{ ...ghostButtonStyle, textAlign: "left", fontSize: 12 }}>
              {e.active ? "Отключить" : "Подключить"}
            </button>
            {tournament.type !== "knockout" && tournament.type !== "tiebreak" && (
              <button onClick={() => runAction(toggleHidden)} style={{ ...ghostButtonStyle, textAlign: "left", fontSize: 12 }}>
                {e.hidden_from_standings ? "В таблице" : "Не в таблице"}
              </button>
            )}
            {tournament.type !== "knockout" && tournament.type !== "tiebreak" && e.active && (
              <button onClick={() => runAction(handleResetToday)} style={{ ...ghostButtonStyle, textAlign: "left", fontSize: 12 }}>
                Сбросить сегодня
              </button>
            )}
          </div>
        )}
        <div style={{ fontSize: 12, marginTop: 6 }}>
          {e.active ? (
            tracksToday ? (
              <span
                style={{ color: todayColor(e), opacity: todayColor(e) ? 1 : 0.7 }}
                title={e.played_today ? "Подключен" : undefined}
              >
                {e.played_today ? playedTodayText(e) : "Подключен"}
              </span>
            ) : (
              <span style={{ opacity: 0.7 }}>Подключен</span>
            )
          ) : (
            <span style={{ opacity: 0.7 }}>Отключен</span>
          )}
          {tournament.type !== "knockout" && tournament.type !== "tiebreak" && e.hidden_from_standings && (
            <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.6, border: "1px solid #3a3a3c", borderRadius: 4, padding: "1px 5px" }}>
              не в таблице
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ margin: 0 }}>Участники «{tournament.title}»</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={refresh} style={{ ...ghostButtonStyle, fontSize: 12 }}>
            Обновить
          </button>
          {availableUsers.length > 0 && (
            <button onClick={handleAddAll} style={{ ...ghostButtonStyle, fontSize: 12 }}>
              Добавить всех
            </button>
          )}
          {activeCount > 0 && (
            <button onClick={handleDisconnectAll} style={{ ...ghostButtonStyle, fontSize: 12 }}>
              Отключить всех
            </button>
          )}
        </div>
      </div>
      <p style={{ opacity: 0.7, fontSize: 13, marginTop: 4 }}>
        Подключено: {activeCount}{inactiveCount > 0 ? ` · Отключено: ${inactiveCount}` : ""}
        {tracksToday && activeCount > 0 && (
          <> · <span style={{ color: "#538d4e" }}>Сыграло сегодня: {playedTodayCount}</span></>
        )}
      </p>
      <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 220px" }}>
          <ClearableInput
            type="text"
            placeholder="Выберите игрока — поиск по заметке"
            value={userQuery}
            onChange={(e) => { setUserQuery(e.target.value); setUserMenuOpen(true); if (userId) setUserId(""); }}
            onFocus={() => setUserMenuOpen(true)}
            onBlur={() => setUserMenuOpen(false)}
            onClear={clearUserSelection}
          />
          {userMenuOpen && shownUsers.length > 0 && (
            <div
              style={{
                position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20, marginTop: 2,
                background: "#1c1c1e", border: "1px solid #3a3a3c", borderRadius: 6,
                maxHeight: 220, overflowY: "auto",
              }}
            >
              {shownUsers.map((u) => (
                <div
                  key={u.id}
                  onMouseDown={(e) => { e.preventDefault(); selectUser(u); }}
                  style={{ padding: "6px 10px", cursor: "pointer", fontSize: 13 }}
                >
                  {u.admin_note || `Игрок #${u.id}`}
                </div>
              ))}
              {matchingUsers.length > shownUsers.length && (
                <div style={{ padding: "6px 10px", fontSize: 12, opacity: 0.6 }}>
                  и ещё {matchingUsers.length - shownUsers.length} — уточните поиск
                </div>
              )}
            </div>
          )}
        </div>
        <ClearableInput
          placeholder="Позывной для этого розыгрыша"
          value={callsign}
          onChange={(e) => setCallsign(e.target.value)}
          onClear={() => setCallsign("")}
          style={{ flex: "1 1 220px" }}
          required
        />
        {tournament.type !== "knockout" && tournament.type !== "tiebreak" && (
          <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, opacity: 0.8, cursor: "pointer" }}>
            <input type="checkbox" checked={hideFromStandings} onChange={(e) => setHideFromStandings(e.target.checked)} />
            не учитывать в таблице
          </label>
        )}
        <button type="submit" style={buttonStyle}>Подключить</button>
      </form>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}
      {transferMsg && (
        <div style={{ fontSize: 13, marginBottom: 8, background: "#242426", borderRadius: 6, padding: "6px 10px" }}>
          {transferMsg}
          <button onClick={() => setTransferMsg(null)} style={{ ...ghostButtonStyle, fontSize: 11, marginLeft: 8, padding: "1px 6px" }}>×</button>
        </div>
      )}

      <ClearableInput
        placeholder="🔎 Поиск по позывному или игроку..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onClear={() => setSearch("")}
        style={{ marginBottom: 8 }}
      />

      {selectedIds.size > 0 && transferTargets.length > 0 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8, background: "#242426", borderRadius: 6, padding: 8 }}>
          <span style={{ fontSize: 13 }}>Выбрано: {selectedIds.size}</span>
          <select value={transferTo} onChange={(e) => setTransferTo(e.target.value)} style={{ ...inputStyle, fontSize: 13 }}>
            <option value="" disabled>Перебросить в...</option>
            {transferTargets.map((t) => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </select>
          <button onClick={handleTransfer} disabled={!transferTo || transferring} style={{ ...buttonStyle, fontSize: 12, opacity: !transferTo || transferring ? 0.6 : 1 }}>
            {transferring ? "Переброс..." : "Перебросить"}
          </button>
          <button onClick={() => setSelectedIds(new Set())} style={{ ...ghostButtonStyle, fontSize: 12 }}>
            Отменить выбор
          </button>
        </div>
      )}

      <div style={{ maxHeight: 360, overflowY: "auto" }}>
        {isMobile ? (
          sortedEntries.map(renderCard)
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7, fontSize: 13 }}>
                {transferTargets.length > 0 && (
                  <th style={thStyle}>
                    {selectableVisible.length > 0 && (
                      <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAllVisible} />
                    )}
                  </th>
                )}
                <th style={thStyle}>Позывной</th>
                <th style={thStyle}>Игрок</th>
                <th style={thStyle}>Статус</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {sortedEntries.map((e) => {
                const u = users.find((x) => x.id === e.user_id);
                const isEditingCallsign = editingCallsignId === e.id;
                return (
                  <tr key={e.id} style={{ borderTop: "1px solid #2a2a2c", opacity: e.active ? 1 : 0.5 }}>
                    {transferTargets.length > 0 && (
                      <td style={tdStyle}>
                        {e.active && (
                          <input type="checkbox" checked={selectedIds.has(e.id)} onChange={() => toggleSelect(e.id)} />
                        )}
                      </td>
                    )}
                    <td style={tdStyle}>
                      {isEditingCallsign ? (
                        <div style={{ display: "flex", gap: 4 }}>
                          <input
                            autoFocus
                            value={callsignForm}
                            onChange={(ev) => setCallsignForm(ev.target.value)}
                            onKeyDown={(ev) => { if (ev.key === "Enter") saveCallsign(e); if (ev.key === "Escape") setEditingCallsignId(null); }}
                            style={{ ...inputStyle, padding: "2px 6px", fontSize: 13, width: 110 }}
                          />
                          <button onClick={() => saveCallsign(e)} style={{ ...buttonStyle, padding: "2px 8px", fontSize: 11 }}>OK</button>
                          <button onClick={() => setEditingCallsignId(null)} style={{ ...ghostButtonStyle, padding: "2px 8px", fontSize: 11 }}>Отмена</button>
                        </div>
                      ) : (
                        <>
                          {e.callsign}
                          <button
                            onClick={() => { setEditingCallsignId(e.id); setCallsignForm(e.callsign); }}
                            title="Изменить позывной"
                            style={{ ...ghostButtonStyle, marginLeft: 6, padding: "0px 6px", fontSize: 11 }}
                          >
                            ✎
                          </button>
                        </>
                      )}
                    </td>
                    <td style={{ ...tdStyle, opacity: 0.7 }}>{u?.admin_note || `Игрок #${e.user_id}`}</td>
                    <td style={tdStyle}>
                      {e.active ? (
                        tracksToday ? (
                          <span
                            title={e.played_today ? "Подключен" : undefined}
                            style={{ color: todayColor(e) }}
                          >
                            {e.played_today ? playedTodayText(e) : "Подключен"}
                          </span>
                        ) : (
                          "Подключен"
                        )
                      ) : (
                        "Отключен"
                      )}
                      {tournament.type !== "knockout" && tournament.type !== "tiebreak" && e.hidden_from_standings && (
                        <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.6, border: "1px solid #3a3a3c", borderRadius: 4, padding: "1px 5px" }}>
                          не в таблице
                        </span>
                      )}
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        <button onClick={() => copyLink(e)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                          {copiedEntryId === e.id ? "Скопировано!" : "Копировать ссылку"}
                        </button>
                        <button onClick={() => toggleActive(e)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                          {e.active ? "Отключить" : "Подключить"}
                        </button>
                        {tournament.type !== "knockout" && tournament.type !== "tiebreak" && (
                          <button onClick={() => toggleHidden(e)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                            {e.hidden_from_standings ? "В таблице" : "Не в таблице"}
                          </button>
                        )}
                        {tournament.type !== "knockout" && tournament.type !== "tiebreak" && e.active && (
                          <button onClick={() => handleResetToday(e)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                            Сбросить сегодня
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {query && filteredEntries.length === 0 && (
        <div style={{ opacity: 0.5, fontSize: 13, marginTop: 8 }}>Никого не найдено.</div>
      )}
    </div>
  );
}

function TodayWordPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [word, setWord] = useState(null);
  const [notApplicable, setNotApplicable] = useState(false);
  const [excluded, setExcluded] = useState(false);
  const [yesterday, setYesterday] = useState(null);

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
  const tournamentIdRef = useLatest(tournament.id);
  const [word, setWord] = useState(null);
  const [override, setOverride] = useState("");
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

function TiebreakWordsPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [queue, setQueue] = useState(null);
  const [overrides, setOverrides] = useState({});
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

  async function handleSetWord(dayNumber) {
    setError("");
    try {
      await api(`/api/admin/tournaments/${tournament.id}/tiebreak-words/${dayNumber}`, {
        method: "POST",
        body: JSON.stringify({ word: (overrides[dayNumber] || "").trim().toLowerCase() }),
      });
      setOverrides((prev) => ({ ...prev, [dayNumber]: "" }));
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
              <>
                <button onClick={() => handleReroll(slot.day_number)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                  Предложить другое
                </button>
                <input
                  placeholder="Своё слово"
                  value={overrides[slot.day_number] || ""}
                  onChange={(e) => setOverrides((prev) => ({ ...prev, [slot.day_number]: e.target.value }))}
                  style={{ ...inputStyle, fontSize: 12, width: 100 }}
                  maxLength={5}
                />
                <button
                  onClick={() => handleSetWord(slot.day_number)}
                  disabled={(overrides[slot.day_number] || "").trim().length !== 5}
                  style={{ ...ghostButtonStyle, fontSize: 12 }}
                >
                  Заменить
                </button>
              </>
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

function TiebreakResultsPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const res = await api(`/api/admin/tournaments/${id}/tiebreak-results`);
      if (tournamentIdRef.current === id) setData(res);
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  if (!data) return null;

  function placeRank(place) {
    if (!place) return Infinity;
    return Number(place.split("-")[0]);
  }
  const rows = [...data.rows].sort((a, b) => placeRank(a.place) - placeRank(b.place) || a.callsign.localeCompare(b.callsign));

  function cellText(cell) {
    if (!cell) return "-";
    return cell.solved ? `${cell.attempts_used}/6` : "X/6";
  }

  // Картинка таблицы тай-брейка с раскладкой по раундам — тот же стиль
  // рисования, что и у "Скачать таблицу" в StandingsPanel (standard), только
  // колонки — раунды, а не дни (см. пункт бэклога).
  function handleDownloadTiebreak() {
    const dpr = window.devicePixelRatio || 1;
    const placeColMin = 40;
    const roundColMin = 50;
    const font = "14px system-ui, sans-serif";
    const measureCanvas = document.createElement("canvas");
    const mctx = measureCanvas.getContext("2d");
    mctx.font = "bold 14px system-ui, sans-serif";
    const callsignCol = Math.max(90, ...rows.map((r) => mctx.measureText(r.callsign).width + 20));
    mctx.font = "bold 13px system-ui, sans-serif";
    const placeCol = Math.max(placeColMin, ...rows.map((r) => mctx.measureText(r.place || "-").width + 16));
    mctx.font = "bold 11px system-ui, sans-serif";
    const roundCol = Math.max(
      roundColMin,
      ...data.rounds.map((r) => mctx.measureText(`Раунд ${r.round_number}`).width + 12)
    );

    const padding = 16;
    const rowHeight = 28;
    const headerHeight = 28;
    const tableWidth = placeCol + callsignCol + roundCol * data.rounds.length;
    const width = tableWidth + padding * 2;
    const height = headerHeight + rowHeight * rows.length + padding * 2;

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
    const roundX = [];
    for (let i = 0; i < data.rounds.length; i++) {
      roundX.push(x);
      x += roundCol;
    }

    ctx.fillStyle = "#f2f2f2";
    ctx.fillRect(padding, tableTop, tableWidth, headerHeight);
    ctx.fillStyle = "#666";
    ctx.font = "bold 12px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Место", colX.place + placeCol / 2, tableTop + headerHeight / 2);
    ctx.textAlign = "left";
    ctx.fillText("Позывной", colX.callsign + 6, tableTop + headerHeight / 2);
    ctx.font = "bold 11px system-ui, sans-serif";
    ctx.textAlign = "center";
    data.rounds.forEach((r, i) => {
      ctx.fillText(`Раунд ${r.round_number}`, roundX[i] + roundCol / 2, tableTop + headerHeight / 2);
    });

    rows.forEach((r, ri) => {
      const rowY = tableTop + headerHeight + ri * rowHeight;
      if (ri % 2 === 1) {
        ctx.fillStyle = "#fafafa";
        ctx.fillRect(padding, rowY, tableWidth, rowHeight);
      }
      ctx.fillStyle = "#1a1a1b";
      ctx.font = "bold " + font;
      ctx.textAlign = "center";
      ctx.fillText(r.place || "-", colX.place + placeCol / 2, rowY + rowHeight / 2);
      ctx.font = font;
      ctx.textAlign = "left";
      ctx.fillText(r.callsign, colX.callsign + 6, rowY + rowHeight / 2);
      ctx.textAlign = "center";
      r.cells.forEach((cell, i) => {
        ctx.fillStyle = cell ? "#1a1a1b" : "#999";
        ctx.fillText(cellText(cell), roundX[i] + roundCol / 2, rowY + rowHeight / 2);
      });
    });

    ctx.strokeStyle = "#ddd";
    ctx.lineWidth = 1;
    for (let ri = 0; ri <= rows.length; ri++) {
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
      a.download = `${tournament.title.replace(/[^\p{L}\p{N}]+/gu, "_")}_тайбрейк.png`;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Результаты тай-брейка</h3>
        <div style={{ display: "flex", gap: 8 }}>
          {data.rounds.length > 0 && (
            <button onClick={handleDownloadTiebreak} style={ghostButtonStyle}>Скачать</button>
          )}
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      {data.rounds.length === 0 ? (
        <p style={{ opacity: 0.7, fontSize: 13, marginTop: 8 }}>Розыгрыш ещё не начался.</p>
      ) : (
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th style={thStyle}>Место</th>
                <th style={thStyle}>Позывной</th>
                {data.rounds.map((r) => (
                  <th key={r.id} style={thStyle} title={r.word}>Раунд {r.round_number}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.entry_id} style={{ borderTop: "1px solid #2a2a2c", opacity: row.active ? 1 : 0.5 }}>
                  <td style={{ ...tdStyle, fontWeight: row.place && !row.place.includes("-") ? 700 : 400 }}>{row.place || "-"}</td>
                  <td style={tdStyle}>{row.callsign}</td>
                  {row.cells.map((cell, i) => (
                    <td key={i} style={tdStyle}>{cellText(cell)}</td>
                  ))}
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

function StandingsPanel({ tournament }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [standings, setStandings] = useState(null);
  // "current" — live-таблица (включает сегодняшний день, если он уже сыгран);
  // число — снимок по состоянию на конкретный уже полностью прошедший день
  // (см. пункт бэклога: тогда копия/картинка тоже строится по этому снимку,
  // а не по live-данным, где не все успели сыграть сегодня).
  const [selectedDay, setSelectedDay] = useState("current");
  const [lastCompletedDay, setLastCompletedDay] = useState(0);
  const [editing, setEditing] = useState(null); // {participantId, day} | null
  const [form, setForm] = useState({ attempts_used: 1, solved: true, note: "" });
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [hoveredCell, setHoveredCell] = useState(null); // {participantId, day} | null
  // Разбор ничьих по итогам тай-брейка (см. пункт бэклога): окончательный порядок
  // внутри групп с общим местом — место со звёздочкой, как "2*".
  const [tieOpen, setTieOpen] = useState(false);
  const [tieData, setTieData] = useState(null); // ответ /tie-groups | null
  const [tieState, setTieState] = useState({}); // place группы -> { use, order, source }
  const [tieBusy, setTieBusy] = useState(false);
  const [tieError, setTieError] = useState("");

  const placeLabel = (r) => `${r.place}${r.tie_resolved ? "*" : ""}`;
  // Пояснение под таблицей в копии и картинке, если есть места, определённые
  // тай-брейком (со звёздочкой)
  const TIE_FOOTNOTE = "* - по результатам тай-брейка";
  const hasTieResolved = () => standings.rows.some((r) => r.tie_resolved);

  function initTieState(data) {
    const next = {};
    for (const g of data.groups) {
      const order = g.applied_order || g.suggested_order || g.members.map((m) => m.entry_id);
      next[g.place] = {
        use: Boolean(g.applied_order || g.suggested_order),
        order,
        source: g.applied_source || g.suggested_source || "вручную",
      };
    }
    setTieState(next);
  }

  async function openTies() {
    setTieOpen(true);
    setTieError("");
    try {
      const data = await api(`/api/admin/tournaments/${tournament.id}/tie-groups`);
      setTieData(data);
      initTieState(data);
    } catch (e) {
      setTieError(e.message);
    }
  }

  function moveTie(place, index, delta) {
    setTieState((prev) => {
      const st = prev[place];
      const order = [...st.order];
      const target = index + delta;
      if (target < 0 || target >= order.length) return prev;
      [order[index], order[target]] = [order[target], order[index]];
      return { ...prev, [place]: { ...st, order, use: true, source: "вручную" } };
    });
  }

  async function saveTies(resolutions) {
    setTieBusy(true);
    setTieError("");
    try {
      const data = await api(`/api/admin/tournaments/${tournament.id}/tie-resolutions`, {
        method: "PUT",
        body: JSON.stringify({ resolutions }),
      });
      setTieData(data);
      initTieState(data);
      await refresh();
    } catch (e) {
      setTieError(e.message);
    } finally {
      setTieBusy(false);
    }
  }

  function handleApplyTies() {
    const resolutions = tieData.groups
      .filter((g) => tieState[g.place]?.use)
      .map((g) => ({ entry_ids: tieState[g.place].order, source: tieState[g.place].source }));
    saveTies(resolutions);
  }

  function handleCopyStandings() {
    const tags = [standings.hashtag, "#таблица", `#д${standings.current_day}`].filter(Boolean).join(" ");
    // "·", а не "N. " — иначе Telegram распознаёт "1. " как начало
    // нумерованного списка и при вставке склеивает все строки в один пункт
    // (см. пункт бэклога)
    const lines = standings.rows.map((r) => `${placeLabel(r)} · ${r.callsign} — ${r.total_points}`);
    const text = `${tags}\n\n${lines.join("\n")}${hasTieResolved() ? `\n\n${TIE_FOOTNOTE}` : ""}`;
    navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => setCopied(false)
    );
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
    const footnoteHeight = hasTieResolved() ? 26 : 0;
    mctx.font = "12px system-ui, sans-serif";
    const footnoteWidth = footnoteHeight ? mctx.measureText(TIE_FOOTNOTE).width : 0;
    const width = Math.max(tableWidth, footnoteWidth) + padding * 2;
    const height = headerHeight + rowHeight * standings.rows.length + padding * 2 + footnoteHeight;

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
      ctx.fillText(placeLabel(r), colX.place + placeCol / 2, rowY + rowHeight / 2);
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

    if (footnoteHeight) {
      ctx.fillStyle = "#666";
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(TIE_FOOTNOTE, padding, tableTop + headerHeight + rowHeight * standings.rows.length + 16);
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

  async function load(day) {
    const id = tournament.id;
    const qs = day === "current" ? "" : `?as_of_day=${day}`;
    const data = await api(`/api/admin/tournaments/${id}/standings${qs}`);
    if (tournamentIdRef.current === id) {
      setStandings(data);
      setLastCompletedDay(data.last_completed_day);
    }
  }

  // "Обновить" и обновление после ручной правки — перезагружают именно
  // выбранный сейчас день (live или снимок), не сбрасывая выбор.
  function refresh() {
    return load(selectedDay);
  }

  function handleDayChange(e) {
    const value = e.target.value;
    const day = value === "current" ? "current" : Number(value);
    setSelectedDay(day);
    setEditing(null);
    setError("");
    load(day);
  }

  useEffect(() => {
    setSelectedDay("current");
    load("current");
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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h3 style={{ marginTop: 0 }}>Таблица</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={selectedDay} onChange={handleDayChange} style={{ ...inputStyle, padding: "4px 8px", fontSize: 13, width: "auto" }}>
            <option value="current">Текущий</option>
            {Array.from({ length: lastCompletedDay }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>День {d}</option>
            ))}
          </select>
          <button onClick={handleCopyStandings} style={ghostButtonStyle}>
            {copied ? "Скопировано!" : "Скопировать таблицу"}
          </button>
          <button onClick={handleDownloadStandings} style={ghostButtonStyle}>Скачать таблицу</button>
          {tournament.type === "standard" && selectedDay === "current"
            && standings.rows.some((r) => r.place.includes("-") || r.tie_resolved) && (
            <button onClick={openTies} style={ghostButtonStyle}>Разобрать ничьи</button>
          )}
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      <p style={{ fontSize: 12, opacity: 0.6, marginTop: -4 }}>
        {selectedDay !== "current" && `Показан снимок таблицы по состоянию на конец дня ${selectedDay}. `}
        Клик по ячейке дня — ручная корректировка результата (исключительные случаи). Наведите на цифру — покажутся попытки этого дня.
      </p>
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}
      {tieOpen && (
        <div style={{ background: "#242426", borderRadius: 6, padding: 10, marginBottom: 12, maxWidth: 560 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            <strong style={{ fontSize: 14 }}>Окончательные места по итогам тай-брейка</strong>
            <button onClick={() => setTieOpen(false)} style={{ ...ghostButtonStyle, fontSize: 11, padding: "1px 8px" }}>Закрыть</button>
          </div>
          {tieError && <div style={{ color: "#e5484d", fontSize: 12, marginTop: 6 }}>{tieError}</div>}
          {!tieData ? (
            !tieError && <p style={{ fontSize: 12, opacity: 0.7 }}>Загрузка...</p>
          ) : !tieData.can_resolve ? (
            <p style={{ fontSize: 12, opacity: 0.8 }}>{tieData.reason}</p>
          ) : tieData.groups.length === 0 ? (
            <p style={{ fontSize: 12, opacity: 0.8 }}>Разделённых мест нет.</p>
          ) : (
            <>
              <p style={{ fontSize: 12, opacity: 0.7, margin: "6px 0" }}>
                Порядок предложен по найденному тай-брейку, его можно поправить стрелками. Места, определённые тай-брейком, помечаются звёздочкой (например, 2*).
              </p>
              {tieData.groups.map((g) => {
                const st = tieState[g.place];
                if (!st) return null;
                const startPlace = parseInt(g.place.split("-")[0], 10);
                const nameOf = (id) => g.members.find((m) => m.entry_id === id)?.callsign || id;
                return (
                  <div key={g.place} style={{ borderTop: "1px solid #3a3a3c", paddingTop: 8, marginTop: 8 }}>
                    <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
                      <input
                        type="checkbox" checked={st.use}
                        onChange={(e) => setTieState((prev) => ({ ...prev, [g.place]: { ...prev[g.place], use: e.target.checked } }))}
                      />
                      <span>Места {g.place} · {g.points} очк.</span>
                      {g.applied_order && <span style={{ color: "#538d4e", fontSize: 12 }}>✓ применено</span>}
                    </label>
                    <div style={{ fontSize: 11, opacity: 0.7, margin: "2px 0 4px 22px" }}>
                      {st.source === "вручную"
                        ? "Порядок задан вручную"
                        : `По тай-брейку «${st.source}»`}
                      {!g.suggested_order && !g.applied_order && g.suggestion_note ? `. ${g.suggestion_note}` : ""}
                    </div>
                    <div style={{ marginLeft: 22 }}>
                      {st.order.map((id, i) => (
                        <div key={id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, padding: "2px 0" }}>
                          <span style={{ width: 28, fontWeight: 700 }}>{startPlace + i}*</span>
                          <span style={{ flex: 1, wordBreak: "break-word" }}>{nameOf(id)}</span>
                          <button
                            onClick={() => moveTie(g.place, i, -1)} disabled={i === 0}
                            style={{ ...ghostButtonStyle, padding: "0 6px", fontSize: 12, opacity: i === 0 ? 0.3 : 1 }}
                          >↑</button>
                          <button
                            onClick={() => moveTie(g.place, i, 1)} disabled={i === st.order.length - 1}
                            style={{ ...ghostButtonStyle, padding: "0 6px", fontSize: 12, opacity: i === st.order.length - 1 ? 0.3 : 1 }}
                          >↓</button>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <button onClick={handleApplyTies} disabled={tieBusy} style={{ ...buttonStyle, fontSize: 12, opacity: tieBusy ? 0.6 : 1 }}>
                  {tieBusy ? "Сохраняю..." : "Применить отмеченные"}
                </button>
                <button onClick={() => saveTies([])} disabled={tieBusy} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                  Сбросить всё
                </button>
              </div>
            </>
          )}
        </div>
      )}
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
              <td style={tdStyle}>{placeLabel(r)}</td>
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
  const tournamentIdRef = useLatest(tournament.id);
  const [rounds, setRounds] = useState(null);
  const [error, setError] = useState("");
  const [overridingRoundId, setOverridingRoundId] = useState(null);
  const [ranks, setRanks] = useState({});
  const [orderNote, setOrderNote] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/tiebreak`);
      if (tournamentIdRef.current === id) {
        setRounds(data);
        setError("");
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
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
  const matchIdRef = useLatest(matchId);
  const [queue, setQueue] = useState(null);
  const [editingNum, setEditingNum] = useState(null);
  const [wordForm, setWordForm] = useState("");
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
                const hasAnySide = m.entry_a_id != null || m.entry_b_id != null;
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

const HALL_MODE_LABEL = { off: "Выключен", test: "Тест", on: "Включён" };
const HALL_MODE_HINT = {
  off: "Зал славы недоступен ни одному игроку.",
  test: "Зал славы виден только выбранному игроку — для проверки перед открытием.",
  on: "Зал славы виден всем игрокам по их персональным ссылкам.",
};
const HALL_IMAGE_KINDS = [
  { key: "table", field: "table_image_id", label: "Таблица" },
  { key: "bracket", field: "bracket_image_id", label: "Сетка" },
  { key: "certificate", field: "certificate_image_id", label: "Сертификат" },
];
const EMPTY_HALL_FORM = { title: "", champion: "", date_start: "", date_end: "", is_current: false };

function HallPanel({ users }) {
  const isMobile = useIsMobile();
  const [settings, setSettings] = useState(null); // сохранённые {mode, test_user_id}
  const [modeDraft, setModeDraft] = useState("off");
  const [testUserDraft, setTestUserDraft] = useState("");
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState("");
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [editingId, setEditingId] = useState(null); // null | "new" | id записи
  const [form, setForm] = useState(EMPTY_HALL_FORM);
  const [busyKey, setBusyKey] = useState(null);
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    Promise.all([api("/api/admin/hall/settings"), api("/api/admin/hall/entries")])
      .then(([s, e]) => {
        setSettings(s);
        setModeDraft(s.mode);
        setTestUserDraft(s.test_user_id ? String(s.test_user_id) : "");
        setEntries(e.entries);
      })
      .catch((e) => setError(e.message));
  }, []);

  const activeUsers = users.filter((u) => !u.archived);
  const userName = (id) => {
    const u = users.find((x) => x.id === id);
    return u ? userLabel(u) : `Игрок #${id}`;
  };
  const settingsDirty = settings && (
    modeDraft !== settings.mode || (modeDraft === "test" && Number(testUserDraft || 0) !== (settings.test_user_id || 0))
  );

  async function handleSaveSettings() {
    setError("");
    try {
      const saved = await api("/api/admin/hall/settings", {
        method: "PUT",
        body: JSON.stringify({ mode: modeDraft, test_user_id: modeDraft === "test" ? Number(testUserDraft) || null : null }),
      });
      setSettings(saved);
      setSettingsSaved(true);
      setTimeout(() => setSettingsSaved(false), 2000);
    } catch (e) {
      setError(e.message);
    }
  }

  function startNew() {
    setError("");
    setEditingId("new");
    setForm(EMPTY_HALL_FORM);
  }

  function startEdit(entry) {
    setError("");
    setEditingId(entry.id);
    setForm({
      title: entry.title, champion: entry.champion,
      date_start: entry.date_start, date_end: entry.date_end, is_current: entry.is_current,
    });
  }

  async function handleSaveEntry() {
    setError("");
    try {
      const isNew = editingId === "new";
      const data = await api(isNew ? "/api/admin/hall/entries" : `/api/admin/hall/entries/${editingId}`, {
        method: isNew ? "POST" : "PATCH",
        body: JSON.stringify(form),
      });
      setEntries(data.entries);
      setEditingId(null);
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleDeleteEntry(entry) {
    if (!window.confirm(`Удалить запись «${entry.title}» вместе с картинками?`)) return;
    setError("");
    try {
      setEntries((await api(`/api/admin/hall/entries/${entry.id}`, { method: "DELETE" })).entries);
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleUpload(entry, kind, file) {
    if (!file) return;
    setError("");
    if (file.size > 3 * 1024 * 1024) {
      setError("Картинка больше 3 МБ — уменьшите её и загрузите снова.");
      return;
    }
    const key = `${entry.id}:${kind}`;
    setBusyKey(key);
    try {
      const res = await fetch(`/api/admin/hall/entries/${entry.id}/images/${kind}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      if (res.status === 401) {
        window.location.href = ADMIN_BASE;
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Не удалось загрузить картинку");
      setEntries(data.entries);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyKey(null);
    }
  }

  async function handleDeleteImage(entry, kind) {
    setError("");
    try {
      setEntries((await api(`/api/admin/hall/entries/${entry.id}/images/${kind}`, { method: "DELETE" })).entries);
    } catch (e) {
      setError(e.message);
    }
  }

  const adminImageUrl = (id) => `/api/admin/hall/image/${id}`;

  function renderForm() {
    const field = (label, input) => (
      <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, opacity: 0.9 }}>
        {label}
        {input}
      </label>
    );
    return (
      <div style={{ ...panelStyle, background: "#242426", marginBottom: 12, display: "grid", gap: 10 }}>
        <div style={{ display: "grid", gap: 10, gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr" }}>
          {field("Название турнира", (
            <input
              value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
              placeholder="Вордл Комбат IV" style={inputStyle} maxLength={120}
            />
          ))}
          {field("Чемпион (позывной)", (
            <input
              value={form.champion} onChange={(e) => setForm((f) => ({ ...f, champion: e.target.value }))}
              style={inputStyle} maxLength={80}
            />
          ))}
          {field("Начало", (
            <input type="date" value={form.date_start} onChange={(e) => setForm((f) => ({ ...f, date_start: e.target.value }))} style={inputStyle} />
          ))}
          {field("Окончание", (
            <input type="date" value={form.date_end} onChange={(e) => setForm((f) => ({ ...f, date_end: e.target.value }))} style={inputStyle} />
          ))}
        </div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
          <input type="checkbox" checked={form.is_current} onChange={(e) => setForm((f) => ({ ...f, is_current: e.target.checked }))} />
          Действующий чемпион (если не отмечено ни у одной записи — берётся самая поздняя по дате окончания)
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleSaveEntry} style={buttonStyle}>Сохранить</button>
          <button onClick={() => setEditingId(null)} style={ghostButtonStyle}>Отмена</button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ ...panelStyle, marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Доступность зала славы</h3>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
          {["off", "test", "on"].map((m) => (
            <button
              key={m}
              onClick={() => setModeDraft(m)}
              style={{
                ...ghostButtonStyle,
                background: modeDraft === m ? "#2a2a2c" : "transparent",
                borderColor: modeDraft === m ? "#538d4e" : "#3a3a3c",
              }}
            >
              {HALL_MODE_LABEL[m]}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 13, opacity: 0.75, marginBottom: 10 }}>{HALL_MODE_HINT[modeDraft]}</div>
        {modeDraft === "test" && (
          <div style={{ marginBottom: 10 }}>
            <select value={testUserDraft} onChange={(e) => setTestUserDraft(e.target.value)} style={{ ...inputStyle, maxWidth: "100%" }}>
              <option value="">— выберите игрока —</option>
              {activeUsers.map((u) => (
                <option key={u.id} value={u.id}>{userLabel(u)}{u.last_callsign ? ` · ${u.last_callsign}` : ""}</option>
              ))}
            </select>
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={handleSaveSettings} disabled={!settingsDirty} style={{ ...buttonStyle, opacity: settingsDirty ? 1 : 0.5 }}>
            {settingsSaved ? "Сохранено!" : "Применить"}
          </button>
          {settings && (
            <span style={{ fontSize: 12, opacity: 0.6 }}>
              Сейчас: {HALL_MODE_LABEL[settings.mode].toLowerCase()}
              {settings.mode === "test" && settings.test_user_id ? ` (${userName(settings.test_user_id)})` : ""}
            </span>
          )}
        </div>
      </div>

      {error && <div style={{ color: "#e5484d", marginBottom: 12 }}>{error}</div>}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 8, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0 }}>Летопись</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setPreview(true)} style={ghostButtonStyle} disabled={!entries}>Предпросмотр как у игрока</button>
          <button onClick={startNew} style={buttonStyle}>+ Запись</button>
        </div>
      </div>

      {editingId === "new" && renderForm()}
      {entries && entries.length === 0 && editingId !== "new" && (
        <div style={{ opacity: 0.7 }}>Записей пока нет. Добавьте первого чемпиона.</div>
      )}

      <div style={{ display: "grid", gap: 12 }}>
        {entries?.map((entry) => (
          <div key={entry.id} style={panelStyle}>
            {editingId === entry.id ? renderForm() : (
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 10 }}>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 16 }}>
                    {entry.title}
                    {entry.is_current && <span style={{ marginLeft: 8, fontSize: 11, color: "#f1c933", border: "1px solid #f1c933", borderRadius: 4, padding: "1px 6px" }}>действующий</span>}
                  </div>
                  <div style={{ fontSize: 13, opacity: 0.8 }}>
                    Чемпион: {entry.champion} · {entry.date_start} — {entry.date_end}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => startEdit(entry)} style={ghostButtonStyle}>Изменить</button>
                  <button onClick={() => handleDeleteEntry(entry)} style={{ ...ghostButtonStyle, color: "#e5484d", borderColor: "#5a2a2c" }}>Удалить</button>
                </div>
              </div>
            )}
            <div style={{ display: "grid", gap: 10, gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)" }}>
              {HALL_IMAGE_KINDS.map((k) => {
                const imageId = entry[k.field];
                const busy = busyKey === `${entry.id}:${k.key}`;
                return (
                  <div key={k.key} style={{ border: "1px solid #3a3a3c", borderRadius: 8, padding: 8 }}>
                    <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>{k.label}</div>
                    {imageId ? (
                      <a href={adminImageUrl(imageId)} target="_blank" rel="noopener noreferrer">
                        <img src={adminImageUrl(imageId)} alt={k.label} style={{ width: "100%", height: 80, objectFit: "contain", background: "#121213", borderRadius: 4 }} />
                      </a>
                    ) : (
                      <div style={{ height: 80, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, opacity: 0.5, background: "#121213", borderRadius: 4 }}>
                        не загружено
                      </div>
                    )}
                    <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                      <label style={{ ...ghostButtonStyle, cursor: busy ? "default" : "pointer", opacity: busy ? 0.5 : 1 }}>
                        {busy ? "Загрузка…" : imageId ? "Заменить" : "Загрузить"}
                        <input
                          type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} disabled={busy}
                          onChange={(e) => { handleUpload(entry, k.key, e.target.files[0]); e.target.value = ""; }}
                        />
                      </label>
                      {imageId && <button onClick={() => handleDeleteImage(entry, k.key)} style={ghostButtonStyle}>Убрать</button>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12, opacity: 0.55, marginTop: 12 }}>
        Картинки: PNG, JPEG или WebP до 3 МБ. Новая картинка заменяет прежнюю.
      </div>

      {preview && entries && (
        <div style={{ position: "fixed", inset: 0, zIndex: 1000, overflow: "auto", background: "#000" }}>
          <div style={{ position: "sticky", top: 0, zIndex: 1500, background: "#1c1c1e", padding: "10px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 13 }}>Предпросмотр: так зал славы видит игрок (независимо от режима доступности)</span>
            <button onClick={() => setPreview(false)} style={ghostButtonStyle}>Закрыть</button>
          </div>
          <HallView entries={entries} imageUrl={adminImageUrl} />
        </div>
      )}
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
