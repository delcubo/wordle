import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import HallView from "../components/HallView.jsx";

// Страница зала славы для игрока — по его персональной ссылке (/play/<токен>/hall).
// Если зал закрыт (или открыт только для тестового игрока), сервер отвечает 403.
export default function HallOfFame() {
  const { token } = useParams();
  const [entries, setEntries] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`/api/game/hall?token=${encodeURIComponent(token)}`)
      .then(async (r) => {
        if (r.status === 404) throw new Error("Эта ссылка недействительна. Запросите новую у организатора.");
        if (!r.ok) throw new Error("Зал славы пока недоступен");
        return r.json();
      })
      .then((data) => setEntries(data.entries))
      .catch((e) => setError(e.message));
  }, [token]);

  const back = (
    <Link to={`/play/${token}`} className="hall-back">← Мои игры</Link>
  );

  if (error) {
    return (
      <div style={{ minHeight: "100vh", background: "#090c0b", color: "#f4f5ef", fontFamily: "Arial, sans-serif", padding: 24, textAlign: "center" }}>
        <p>{error}</p>
        {!error.startsWith("Эта ссылка") && <Link to={`/play/${token}`} style={{ color: "#a2aaa5" }}>← Мои игры</Link>}
      </div>
    );
  }
  if (!entries) return <div style={{ minHeight: "100vh", background: "#090c0b" }} />;

  return (
    <HallView
      entries={entries}
      imageUrl={(id) => `/api/game/hall/image/${id}?token=${encodeURIComponent(token)}`}
      back={back}
    />
  );
}
