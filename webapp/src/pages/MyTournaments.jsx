import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchTheme, themeVars } from "../theme.js";

const STATUS_LABEL = { draft: "не начался", active: "идёт", tiebreak: "тай-брейк", playoff: "плей-офф", finished: "завершён" };
const TYPE_LABEL = { standard: "Стандартный", knockout: "На вылет", championship: "Чемпионат", endless: "Бессрочная игра", tiebreak: "Тай-брейк" };

export default function MyTournaments() {
  const { token } = useParams();
  const [tournaments, setTournaments] = useState(null);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState("dark");
  const [hallAvailable, setHallAvailable] = useState(false);

  useEffect(() => {
    // ссылка на зал славы показывается, только когда он открыт для этого игрока
    fetch(`/api/game/hall/status?token=${encodeURIComponent(token)}`)
      .then((r) => (r.ok ? r.json() : { available: false }))
      .then((d) => setHallAvailable(!!d.available))
      .catch(() => setHallAvailable(false));
  }, [token]);

  useEffect(() => {
    fetch(`/api/game/my-tournaments?token=${encodeURIComponent(token)}`)
      .then((r) => {
        if (!r.ok) throw new Error("Ссылка недействительна");
        return r.json();
      })
      .then(setTournaments)
      .catch((e) => setError(e.message));
  }, [token]);

  useEffect(() => {
    fetchTheme().then(setTheme);
  }, []);

  return (
    <div style={{ ...pageStyle, ...themeVars(theme) }}>
      <h2>Мои игры</h2>
      {error && <div style={{ color: "var(--error)" }}>{error}</div>}
      {tournaments && tournaments.length === 0 && <div style={{ opacity: 0.7 }}>Вы пока не подключены ни к одному розыгрышу.</div>}
      <div style={{ width: 320 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {tournaments?.map((t) => (
            <Link
              key={t.tournament_id}
              to={`/play/${token}/${t.tournament_id}`}
              style={cardStyle}
            >
              <div style={{ fontWeight: 600 }}>{t.title}</div>
              <div style={{ fontSize: 13, opacity: 0.7 }}>
                {TYPE_LABEL[t.type] || t.type} · {STATUS_LABEL[t.status] || t.status} · ваш позывной: {t.callsign}
              </div>
            </Link>
          ))}
        </div>
        {hallAvailable && (
          <>
            {/* линия отделяет зал славы от розыгрышей; отступы до и после — одинаковые */}
            {tournaments && tournaments.length > 0 && (
              <div style={{ borderTop: "1px solid var(--border)", margin: "18px 0" }} />
            )}
            <Link to={`/play/${token}/hall`} style={{ ...hallStyle, ...(theme === "light" ? hallLight : hallDark) }}>
              <img src="/hall-emblem.webp" alt="" style={{ ...emblemStyle, boxShadow: `0 0 0 1.5px ${theme === "light" ? "#c9a24c" : "#a98a3f"}` }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 15, color: "var(--fg)" }}>Зал славы</div>
                <div style={{ fontSize: 12, marginTop: 2, color: theme === "light" ? "#5f6b5b" : "#8f9c8f" }}>Хроника чемпионов</div>
              </div>
              <span style={{ fontSize: 20, color: "#6f8a63" }}>›</span>
            </Link>
          </>
        )}
      </div>
    </div>
  );
}

const pageStyle = {
  minHeight: "100vh",
  background: "var(--bg)",
  color: "var(--fg)",
  fontFamily: "system-ui, sans-serif",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  paddingTop: 24,
  gap: 16,
};

const cardStyle = {
  display: "block",
  padding: 12,
  borderRadius: 8,
  border: "1px solid var(--border)",
  background: "var(--bg-secondary)",
  color: "var(--fg)",
  textDecoration: "none",
};

// Зал славы — спокойный баннер: выше карточек розыгрышей, с эмблемой, приглушённые
// зелёные тона вместо ярких цветов самой страницы зала.
const hallStyle = {
  display: "flex",
  alignItems: "center",
  gap: 12,
  minHeight: 64,
  padding: "12px 14px",
  borderRadius: 10,
  textDecoration: "none",
  boxSizing: "border-box",
};
const hallLight = { border: "1px solid #bccdb3", background: "#eef3ea" };
const hallDark = { border: "1px solid #3d4f3f", background: "#192119" };
const emblemStyle = { width: 42, height: 42, borderRadius: "50%", objectFit: "cover", flex: "none", background: "#0b0f0c" };
