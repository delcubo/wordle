import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ADMIN_BASE } from "../adminBase.js";

export default function AdminLogin() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) {
      // 429 — слишком много неудачных попыток (см. api/admin_auth.py), текст
      // с оставшимся временем приходит с сервера
      const err = await res.json().catch(() => ({}));
      setError(res.status === 429 ? err.detail || "Слишком много попыток, повторите позже" : "Неверный пароль");
      return;
    }
    navigate(`${ADMIN_BASE}/dashboard`);
  }

  return (
    <div style={pageStyle}>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10, width: 280 }}>
        <h2>Вход администратора</h2>
        <input
          type="password"
          placeholder="Пароль"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={inputStyle}
          autoFocus
        />
        {error && <div style={{ color: "#e5484d" }}>{error}</div>}
        <button type="submit" style={buttonStyle}>Войти</button>
      </form>
    </div>
  );
}

const pageStyle = {
  minHeight: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#121213",
  color: "#fff",
  fontFamily: "system-ui, sans-serif",
};

const inputStyle = {
  padding: "10px 12px",
  borderRadius: 6,
  border: "1px solid #3a3a3c",
  background: "#1c1c1e",
  color: "#fff",
  fontSize: 16,
};

const buttonStyle = {
  padding: "10px 12px",
  borderRadius: 6,
  border: "none",
  background: "#538d4e",
  color: "#fff",
  fontSize: 16,
  cursor: "pointer",
};
