import { Suspense, lazy, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ADMIN_BASE } from "../adminBase.js";
import TodayPanel from "./TodayPanel.jsx";
import { ModesContext, STATUS_LABEL, api, ghostButtonStyle, modeHelpers, useIsMobile } from "./adminShared.jsx";
import { TournamentSettings } from "./TournamentForm.jsx";
import { ConfirmHost } from "./confirmDialog.jsx";
import { TournamentPanel } from "./admin/TournamentPanel.jsx";
import { EntriesPanel } from "./admin/EntriesPanel.jsx";
import { MarathonIndividualWordsPanel, MarathonWordsPanel } from "./admin/MarathonWords.jsx";
import { MarathonStandingsPanel, MarathonTeamStandingsPanel } from "./admin/MarathonResults.jsx";
import { MarathonTeamsPanel } from "./admin/MarathonTeams.jsx";
import { BonusWordsPanel, TodayWordPanel, WordConfirmPanel, WordHistoryPanel } from "./admin/DailyWords.jsx";
import { TiebreakTeamWordsPanel, TiebreakWordsPanel } from "./admin/TiebreakWords.jsx";
import { TiebreakResultsPanel, TiebreakTeamResultsPanel } from "./admin/TiebreakResults.jsx";
import { StandingsPanel } from "./admin/StandingsPanel.jsx";
import { TiebreakPanel } from "./admin/TiebreakPanel.jsx";
import { TiebreakReopen } from "./admin/TiebreakReopen.jsx";
import { BracketPanel } from "./admin/Bracket.jsx";

// Редко нужные вкладки грузятся отдельными файлами, только когда их открывают
const UsersPanel = lazy(() => import("./admin/UsersPanel.jsx").then((m) => ({ default: m.UsersPanel })));
const DictionaryPanel = lazy(() => import("./admin/DictionaryPanel.jsx").then((m) => ({ default: m.DictionaryPanel })));
const HallPanel = lazy(() => import("./admin/HallPanel.jsx").then((m) => ({ default: m.HallPanel })));

// Подвкладки страницы розыгрыша — по модулям режима (реестр: api/modes.py).
function subtabsFor(t, has) {
  const any = (...modules) => modules.some((m) => has(t.type, m));
  const tabs = [{ key: "participants", label: "Участники" }];
  if (any("daily_words", "marathon_words", "tiebreak_words")) tabs.push({ key: "words", label: "Слова" });
  if (any("standings", "marathon_results", "tiebreak_results")) tabs.push({ key: "results", label: "Результаты" });
  if (any("playoff")) tabs.push({ key: "bracket", label: t.type === "championship" ? "Плей-офф" : "Сетка" });
  tabs.push({ key: "settings", label: "Настройки" });
  return tabs;
}

// Что видит админ на телефоне: цели для пальца не меньше ~38px, широкие таблицы прокручиваются внутри себя.
const MOBILE_CSS = `
.admin-root button, .admin-root select, .admin-root input:not([type=checkbox]):not([type=radio]) { min-height: 38px; }
.admin-root table { display: block; max-width: 100%; overflow-x: auto; }
`;

export default function AdminDashboard() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  // вкладка, розыгрыш и подвкладка — в адресе (?tab=…&id=…&sub=…): работают «назад» и ссылка на экран
  const [params, setParams] = useSearchParams();
  const [tournaments, setTournaments] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState("dark");
  const [teamsVersion, setTeamsVersion] = useState(0); // меняется при правке команд — командная таблица перечитывается
  const [entriesVersion, setEntriesVersion] = useState(0); // меняется при удалении игрока — панели тай-брейка перечитываются
  const [modes, setModes] = useState(() => modeHelpers([]));
  const [needConfirm, setNeedConfirm] = useState(0); // сколько слов на завтра ждут подтверждения (значок на вкладке «Сегодня»)
  const [headerH, setHeaderH] = useState(0);
  const scrollPending = useRef(false);
  const headerRef = useRef(null);
  const contentRef = useRef(null);

  const tab = params.get("tab") || "today";
  // По умолчанию — первый неархивный розыгрыш, а не просто первый в списке
  // (иначе при первой загрузке могло открыться меню архивного розыгрыша).
  const firstLive = tournaments.find((t) => !t.archived) || tournaments[0] || null;
  const selected = tournaments.find((t) => String(t.id) === params.get("id")) || firstLive;
  const { has, label: modeLabel } = modes;
  const subtabs = selected ? subtabsFor(selected, has) : [];
  const sub = subtabs.some((s) => s.key === params.get("sub")) ? params.get("sub") : "participants";

  function go(patch) {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v == null ? next.delete(k) : next.set(k, String(v))));
    setParams(next);
  }

  function openTournament(id, subKey) {
    scrollPending.current = true;
    go({ tab: "tournaments", id, sub: subKey });
  }

  async function refreshTournaments() {
    setTournaments(await api("/api/admin/tournaments"));
  }

  async function refreshUsers() {
    setUsers(await api("/api/admin/users"));
  }

  async function refreshTheme() {
    setTheme((await api("/api/admin/settings/theme")).theme);
  }

  async function loadModes() {
    setModes(modeHelpers(await api("/api/admin/modes")));
  }

  useEffect(() => {
    api("/api/admin/me")
      .then(() => Promise.all([refreshTournaments(), refreshUsers(), refreshTheme(), loadModes()]))
      .catch(() => {})
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // высота закреплённой шапки — чтобы панель подвкладок прилипала прямо под ней
  useLayoutEffect(() => {
    function measure() {
      setHeaderH(headerRef.current ? headerRef.current.offsetHeight : 0);
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [loading, isMobile]);

  // «Открыть →» из «Сегодня» и выбор розыгрыша из списка: прокрутить к его содержимому (на телефоне
  // список розыгрышей идёт выше). Адрес меняется позже состояния, поэтому ждём, пока блок появится.
  useEffect(() => {
    if (scrollPending.current && tab === "tournaments" && contentRef.current) {
      scrollPending.current = false;
      // список розыгрыша выше ещё дорисовывается — прокручиваем после этого
      setTimeout(() => contentRef.current && contentRef.current.scrollIntoView({ block: "start" }), 150);
    }
  });

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
    <ModesContext.Provider value={modes}>
    <div className="admin-root" style={{ minHeight: "100vh", background: "#121213", color: "#fff", fontFamily: "system-ui, sans-serif" }}>
      {isMobile && <style>{MOBILE_CSS}</style>}
      <ConfirmHost />
      <div
        ref={headerRef}
        style={{ position: "sticky", top: 0, zIndex: 10, background: "#121213", padding: isMobile ? "10px 12px 0" : "20px 20px 0", borderBottom: "1px solid #2a2a2c" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: isMobile ? 8 : 16, gap: 8 }}>
          <h1 style={{ margin: 0, fontSize: isMobile ? 18 : undefined }}>{isMobile ? "Админка" : "Админ-панель · Вордли"}</h1>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button onClick={handleToggleTheme} style={{ ...ghostButtonStyle, whiteSpace: "nowrap" }} title="Тема оформления для игроков (не влияет на саму админ-панель)">
              {isMobile ? "Тема" : "Тема игроков"}: {theme === "dark" ? "тёмная" : "светлая"}
            </button>
            <button onClick={handleLogout} style={ghostButtonStyle}>Выйти</button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, paddingBottom: 12, overflowX: "auto" }}>
          <TabButton active={tab === "today"} onClick={() => go({ tab: "today" })}>
            Сегодня{needConfirm > 0 ? ` (${needConfirm})` : ""}
          </TabButton>
          <TabButton active={tab === "tournaments"} onClick={() => go({ tab: "tournaments" })}>Розыгрыши</TabButton>
          <TabButton active={tab === "users"} onClick={() => go({ tab: "users" })}>Игроки</TabButton>
          <TabButton active={tab === "dictionary"} onClick={() => go({ tab: "dictionary" })}>Словарь</TabButton>
          <TabButton active={tab === "hall"} onClick={() => go({ tab: "hall" })}>Зал славы</TabButton>
        </div>
      </div>

      <div style={{ padding: isMobile ? 12 : 20 }}>
      {tab === "today" && <TodayPanel onOpen={openTournament} onNeedConfirmChange={setNeedConfirm} />}
      <Suspense fallback={<div style={{ opacity: 0.7 }}>Загрузка…</div>}>
        {tab === "users" && <UsersPanel users={users} onChanged={refreshUsers} />}
        {tab === "dictionary" && <DictionaryPanel />}
        {tab === "hall" && <HallPanel users={users} />}
      </Suspense>

      {tab === "tournaments" && (
        <div style={isMobile ? { display: "flex", flexDirection: "column", gap: 24 } : { display: "flex", gap: 24, flexWrap: "wrap" }}>
          <div style={isMobile ? {} : { flex: "1 1 300px" }}>
            <TournamentPanel
              tournaments={tournaments}
              selected={selected}
              onSelect={(t) => { if (isMobile) scrollPending.current = true; go({ id: t.id }); }}
              onCreated={refreshTournaments}
              onActivated={refreshTournaments}
              onOpenSettings={(t) => openTournament(t.id, "settings")}
            />
          </div>
          <div ref={contentRef} style={{ ...(isMobile ? {} : { flex: "2 1 500px" }), scrollMarginTop: headerH + 8, minWidth: 0 }}>
            {selected ? (
              <>
                <div style={{ position: "sticky", top: headerH, zIndex: 5, background: "#121213", padding: "8px 0" }}>
                  {!isMobile && (
                    <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                      <b style={{ fontSize: 16 }}>{selected.title}</b>
                      <span style={{ fontSize: 12, opacity: 0.7 }}>{modeLabel(selected.type)} · {STATUS_LABEL[selected.status] || selected.status}</span>
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 6, overflowX: "auto" }}>
                    {subtabs.map((s) => (
                      <TabButton key={s.key} active={sub === s.key} onClick={() => go({ sub: s.key })}>{s.label}</TabButton>
                    ))}
                  </div>
                </div>

                {sub === "participants" && (
                  <>
                    <EntriesPanel
                      tournament={selected} users={users} allTournaments={tournaments}
                      onEntriesChanged={() => setEntriesVersion((v) => v + 1)}
                    />
                    {has(selected.type, "teams") && selected.teams_enabled && (
                      <MarathonTeamsPanel tournament={selected} refreshKey={entriesVersion} onChanged={() => setTeamsVersion((v) => v + 1)} />
                    )}
                  </>
                )}

                {sub === "words" && (
                  <>
                    {has(selected.type, "tiebreak_words") && (
                      selected.teams_enabled
                        ? <TiebreakTeamWordsPanel tournament={selected} refreshKey={entriesVersion} />
                        : <TiebreakWordsPanel tournament={selected} />
                    )}
                    {has(selected.type, "marathon_words") && (
                      selected.individual_words
                        ? <MarathonIndividualWordsPanel tournament={selected} onTournamentChanged={refreshTournaments} />
                        : <MarathonWordsPanel tournament={selected} onTournamentChanged={refreshTournaments} />
                    )}
                    {has(selected.type, "daily_words") && <TodayWordPanel tournament={selected} />}
                    {has(selected.type, "daily_words") && <WordConfirmPanel tournament={selected} />}
                    {has(selected.type, "daily_words") && <WordHistoryPanel tournament={selected} />}
                    {has(selected.type, "bonus") && selected.bonus_enabled && (
                      <BonusWordsPanel tournament={selected} />
                    )}
                  </>
                )}

                {sub === "results" && (
                  <>
                    {has(selected.type, "tiebreak_results") && selected.status === "finished" && (
                      <TiebreakReopen tournament={selected} onChanged={refreshTournaments} />
                    )}
                    {has(selected.type, "tiebreak_results") && (
                      selected.teams_enabled
                        ? <TiebreakTeamResultsPanel tournament={selected} refreshKey={entriesVersion} />
                        : <TiebreakResultsPanel tournament={selected} refreshKey={entriesVersion} />
                    )}
                    {has(selected.type, "marathon_results") && selected.teams_enabled && (
                      <MarathonTeamStandingsPanel
                        tournament={selected} refreshKey={teamsVersion} tournaments={tournaments}
                        onTournamentsChanged={refreshTournaments}
                      />
                    )}
                    {has(selected.type, "marathon_results") && <MarathonStandingsPanel tournament={selected} />}
                    {has(selected.type, "standings") && <StandingsPanel tournament={selected} />}
                  </>
                )}

                {sub === "bracket" && (
                  <>
                    {has(selected.type, "tiebreak_phase") && <TiebreakPanel tournament={selected} onTournamentChanged={refreshTournaments} />}
                    <BracketPanel tournament={selected} onTournamentChanged={refreshTournaments} />
                  </>
                )}

                {sub === "settings" && (
                  <TournamentSettings key={selected.id} tournament={selected} onSaved={refreshTournaments} />
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
    </ModesContext.Provider>
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

function Centered({ children }) {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#121213", color: "#fff" }}>
      {children}
    </div>
  );
}
