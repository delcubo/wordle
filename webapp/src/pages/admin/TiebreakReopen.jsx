import { useState } from "react";
import { api, buttonStyle, inputStyle, panelStyle } from "../adminShared.jsx";
import { askConfirm } from "../confirmDialog.jsx";

// Завершённый тай-брейк можно вернуть в игру, чтобы доиграл тот, кто не успел и получил пропуск.
export function TiebreakReopen({ tournament, onChanged }) {
  const [endDate, setEndDate] = useState(() => new Date().toLocaleDateString("sv-SE"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleReopen() {
    setError("");
    const day = endDate.split("-").reverse().join(".");
    if (!await askConfirm(
      `Вернуть «${tournament.title}» в игру? Раунды, где кто-то не доиграл, откроются снова, срок будет до конца ${day} включительно. Когда все доиграют (или срок выйдет), места пересчитаются, и розыгрыш завершится сам.`
    )) return;
    setBusy(true);
    try {
      await api(`/api/admin/tournaments/${tournament.id}/tiebreak/reopen`, { method: "POST", body: JSON.stringify({ end_date: endDate }) });
      if (onChanged) await onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ ...panelStyle, marginBottom: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>Розыгрыш завершён</div>
      <div style={{ fontSize: 13, opacity: 0.75, marginBottom: 8 }}>
        Если кто-то не успел сыграть и получил пропуск, его можно вернуть в игру: сыгранные результаты сохранятся.
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13 }}>
          Доиграть до{" "}
          <input type="date" value={endDate} min={new Date().toLocaleDateString("sv-SE")} onChange={(e) => setEndDate(e.target.value)} style={{ ...inputStyle, padding: "4px 8px" }} />
        </label>
        <button onClick={handleReopen} disabled={busy || !endDate} style={buttonStyle}>Вернуть в игру</button>
      </div>
      {error && <div style={{ color: "#e5484d", marginTop: 8 }}>{error}</div>}
    </div>
  );
}
