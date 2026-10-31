import { useEffect, useState } from "react";
import { ADMIN_BASE } from "../../adminBase.js";
import HallView from "../../components/HallView.jsx";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, useIsMobile, userLabel } from "../adminShared.jsx";
import { askConfirm } from "../confirmDialog.jsx";

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

export function HallPanel({ users }) {
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
    if (!await askConfirm(`Удалить запись «${entry.title}» вместе с картинками?`)) return;
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
