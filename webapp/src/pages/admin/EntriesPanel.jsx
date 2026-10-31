import { useEffect, useState } from "react";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, tdStyle, thStyle, useIsMobile, useLatest, useModes } from "../adminShared.jsx";
import { askConfirm } from "../confirmDialog.jsx";

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

export function EntriesPanel({ tournament, users, allTournaments, onEntriesChanged }) {
  const isMobile = useIsMobile();
  const { has } = useModes();
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
  const tracksToday = has(tournament.type, "tracks_today");
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
    if (!await askConfirm(`Перебросить выбранных игроков (${selectedIds.size}) в «${target.title}»? В «${tournament.title}» они будут отключены (статистика останется).`)) {
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
    if (entry.active && !await askConfirm(`Отключить «${entry.callsign}» от розыгрыша? Набранная статистика останется в таблице.`)) {
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

  // Удалить игрока из тай-брейка совсем (в отличие от «Отключить» — результаты стираются, из таблицы и
  // распределения мест он пропадает). Необратимо, поэтому с подтверждением.
  async function handleDeleteEntry(entry) {
    const teamNote = tournament.teams_enabled ? " Средние команд и места пересчитаются без него." : "";
    if (!await askConfirm(
      `Удалить «${entry.callsign}» из тай-брейка «${tournament.title}»?\n\nЕго результаты и слова будут стёрты, он исчезнет из таблицы и из распределения мест.${teamNote}\n\nЭто нельзя отменить: подключить игрока заново можно, но его результаты не вернутся.`
    )) {
      return;
    }
    setError("");
    try {
      await api(`/api/admin/entries/${entry.id}`, { method: "DELETE" });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(entry.id);
        return next;
      });
      await refresh();
      if (onEntriesChanged) onEntriesChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleResetToday(entry) {
    if (!await askConfirm(`Сбросить попытку «${entry.callsign}» за сегодня? Игрок сможет сыграть сегодняшнее слово заново с нуля — введённые буквы и результат за сегодня будут стёрты без возможности отмены.`)) {
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
    if (!await askConfirm(`Отключить всех подключённых участников (${activeCount}) от «${tournament.title}»? Набранная статистика останется в таблице, подключить обратно можно по одному.`)) {
      return;
    }
    await api(`/api/admin/tournaments/${tournament.id}/entries/disconnect-all`, { method: "POST" });
    refresh();
  }

  async function handleAddAll() {
    if (!await askConfirm(`Подключить сразу всех зарегистрированных игроков (${availableUsers.length}) к «${tournament.title}»? Позывные подставятся по умолчанию (заметка админа или «#игрокN») — их можно будет переименовать позже.`)) {
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
            {tournament.type === "tiebreak" && (
              <button
                onClick={() => runAction(handleDeleteEntry)}
                style={{ ...ghostButtonStyle, textAlign: "left", fontSize: 12, color: "#e5484d", borderColor: "#e5484d" }}
              >
                Удалить из розыгрыша
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
                        {tournament.type === "tiebreak" && (
                          <button
                            onClick={() => handleDeleteEntry(e)}
                            title="Стереть игрока из тай-брейка: из таблицы и распределения мест"
                            style={{ ...ghostButtonStyle, fontSize: 12, color: "#e5484d", borderColor: "#e5484d" }}
                          >
                            Удалить из розыгрыша
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
