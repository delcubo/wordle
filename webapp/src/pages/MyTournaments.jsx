import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchTheme, themeVars } from "../theme.js";

const STATUS_LABEL = { draft: "не начался", active: "идёт", tiebreak: "тай-брейк", playoff: "плей-офф", finished: "завершён" };
const TYPE_LABEL = { standard: "Стандартный", knockout: "На вылет", championship: "Чемпионат", endless: "Бессрочная игра" };

export default function MyTournaments() {
  const { token } = useParams();
  const [tournaments, setTournaments] = useState(null);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState("dark");

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
      <h2>Мои розыгрыши</h2>
      {error && <div style={{ color: "var(--error)" }}>{error}</div>}
      {tournaments && tournaments.length === 0 && <div style={{ opacity: 0.7 }}>Вы пока не подключены ни к одному розыгрышу.</div>}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, width: 320 }}>
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
