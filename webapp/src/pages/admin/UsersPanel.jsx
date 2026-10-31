import { useState } from "react";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, tdStyle, thStyle, useIsMobile, userLabel } from "../adminShared.jsx";
import { askConfirm } from "../confirmDialog.jsx";

export function UsersPanel({ users, onChanged }) {
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
    if (!await askConfirm(
      `Отключить «${u.admin_note || `Игрок #${u.id}`}» от всех розыгрышей? ` +
      `Личная ссылка продолжит работать, статистика сохранится.`
    )) {
      return;
    }
    await api(`/api/admin/users/${u.id}/disconnect`, { method: "POST" });
    onChanged();
  }

  async function handleArchive(u) {
    if (!await askConfirm(
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
    if (!await askConfirm(
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
