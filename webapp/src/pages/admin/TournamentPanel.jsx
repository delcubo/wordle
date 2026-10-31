import { useState } from "react";
import { STATUS_LABEL, api, buttonStyle, ghostButtonStyle, panelStyle, useModes } from "../adminShared.jsx";
import { CreateWizard, summaryOf } from "../TournamentForm.jsx";

export function TournamentPanel({ tournaments, selected, onSelect, onCreated, onActivated, onOpenSettings }) {
  const { label } = useModes();
  const [showWizard, setShowWizard] = useState(false);
  const [showArchive, setShowArchive] = useState(false);

  async function handleTogglePause(t) {
    await api(`/api/admin/tournaments/${t.id}/pause`, { method: "PATCH", body: JSON.stringify({ paused: !t.paused }) });
    onActivated();
  }

  async function handleToggleArchived(t) {
    await api(`/api/admin/tournaments/${t.id}/archive`, { method: "PATCH", body: JSON.stringify({ archived: !t.archived }) });
    onActivated();
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
          {t.archived && t.players_connected > 0 && (
            <span
              title="В этом архивном розыгрыше ещё есть подключённые игроки: они видят его в «Моих играх»"
              style={{ marginLeft: 6, fontSize: 11, color: "#e5a94c", border: "1px solid #e5a94c", borderRadius: 4, padding: "1px 5px" }}
            >
              👥 {t.players_connected}
            </span>
          )}
          {t.paused && (
            <span style={{ marginLeft: 6, fontSize: 11, color: "#e5a94c", border: "1px solid #e5a94c", borderRadius: 4, padding: "1px 5px" }}>
              приостановлен
            </span>
          )}
        </div>
        <div style={{ fontSize: 13, opacity: 0.7 }}>
          {label(t.type)} · {summaryOf(t)} · {STATUS_LABEL[t.status] || t.status}
        </div>
        {t.note && (
          <div style={{ fontSize: 12, opacity: 0.6, marginTop: 4, whiteSpace: "pre-wrap" }}>{t.note}</div>
        )}
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
            onClick={(e) => { e.stopPropagation(); onOpenSettings(t); }}
            style={{ ...ghostButtonStyle, fontSize: 12 }}
          >
            Настройки
          </button>
        </div>
      </div>
    );
  }

  const liveTournaments = tournaments.filter((t) => !t.archived);
  const archivedTournaments = tournaments.filter((t) => t.archived);
  // архивные розыгрыши, где ещё есть подключённые игроки, — отдельным блоком наверху архива
  const archivedWithPlayers = archivedTournaments.filter((t) => t.players_connected > 0);
  const archivedByYear = {};
  for (const t of archivedTournaments.filter((x) => !(x.players_connected > 0))) {
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
            {archivedWithPlayers.length > 0 && (
              <span style={{ color: "#e5a94c" }}> · с игроками: {archivedWithPlayers.length}</span>
            )}
          </button>
          {showArchive && archivedWithPlayers.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, color: "#e5a94c", marginBottom: 4 }}>С подключёнными игроками</div>
              {archivedWithPlayers.map(renderCard)}
            </div>
          )}
          {showArchive && archivedYears.map((year) => (
            <div key={year} style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 4 }}>{year}</div>
              {archivedByYear[year].map(renderCard)}
            </div>
          ))}
        </div>
      )}

      {!showWizard ? (
        <button onClick={() => setShowWizard(true)} style={buttonStyle}>+ Новый розыгрыш</button>
      ) : (
        <CreateWizard
          onCreated={async () => { setShowWizard(false); await onCreated(); }}
          onCancel={() => setShowWizard(false)}
        />
      )}
    </div>
  );
}
