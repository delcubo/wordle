import { useEffect, useState } from "react";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, tdStyle, useLatest } from "../adminShared.jsx";
import { LengthPlanGrid, saveWordPlanPart } from "./wordPlans.jsx";

export function TiebreakPanel({ tournament, onTournamentChanged }) {
  const tournamentIdRef = useLatest(tournament.id);
  const [rounds, setRounds] = useState(null);
  const [error, setError] = useState("");
  const [overridingRoundId, setOverridingRoundId] = useState(null);
  const [ranks, setRanks] = useState({});
  const [orderNote, setOrderNote] = useState("");

  async function refresh() {
    const id = tournament.id;
    try {
      const data = await api(`/api/admin/tournaments/${id}/tiebreak`);
      if (tournamentIdRef.current === id) {
        setRounds(data);
        setError("");
      }
    } catch (e) {
      if (tournamentIdRef.current === id) setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournament.id]);

  async function handleStart() {
    setError("");
    try {
      const res = await api(`/api/admin/tournaments/${tournament.id}/tiebreak/start`, { method: "POST" });
      if (!res.started) setError("Тай-брейк не нужен — равных мест на границе сетки нет.");
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  function startOverride(round) {
    setError("");
    setOverridingRoundId(round.id);
    const initial = {};
    round.participants.forEach((p, i) => { initial[p.entry_id] = i + 1; });
    setRanks(initial);
    setOrderNote("");
  }

  async function handleSubmitOrder(round) {
    setError("");
    try {
      const order = [...round.participants]
        .sort((a, b) => (Number(ranks[a.entry_id]) || 0) - (Number(ranks[b.entry_id]) || 0))
        .map((p) => p.entry_id);
      await api(`/api/admin/tiebreak/rounds/${round.id}/override`, {
        method: "POST",
        body: JSON.stringify({ order, note: orderNote }),
      });
      setOverridingRoundId(null);
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div style={{ ...panelStyle, marginTop: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ marginTop: 0 }}>Тай-брейк</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleStart} style={buttonStyle}>Запустить тай-брейк</button>
          <button onClick={refresh} style={ghostButtonStyle}>Обновить</button>
        </div>
      </div>
      <LengthPlanGrid
        title="Длины слов по раундам тай-брейка" colLabel="Раунд" slots={3} base={tournament.word_length || 5}
        hint="Длина слова раунда тай-брейка по его номеру в цепочке (после ничьей — следующий раунд). Действует на ещё не созданные раунды; дальше повторяется последнее значение."
        rows={[{ key: "tiebreak", label: "Длина слова" }]}
        plan={tournament.word_plan?.tiebreak ? { tiebreak: tournament.word_plan.tiebreak } : null}
        onSave={async (value) => {
          await saveWordPlanPart(tournament, "tiebreak", value ? value.tiebreak : null);
          if (onTournamentChanged) await onTournamentChanged();
        }}
      />
      {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}
      {rounds && rounds.length === 0 && (
        <div style={{ opacity: 0.7, fontSize: 13 }}>
          Раундов пока нет — запустите тай-брейк после окончания основного этапа.
        </div>
      )}
      {rounds && rounds.map((r) => (
        <div key={r.id} style={{ border: "1px solid #3a3a3c", borderRadius: 6, padding: 10, marginTop: 8 }}>
          <div style={{ fontSize: 13, opacity: 0.7, marginBottom: 4 }}>
            Раунд {r.round_number}{r.previous_round_id ? ` (продолжение раунда #${r.previous_round_id})` : ""} ·{" "}
            слово: <b style={{ textTransform: "uppercase" }}>{r.word}</b> ·{" "}
            {r.completed ? "завершён" : "идёт"}
            {r.manual_order && (
              <span title={`Скорректировано: ${r.admin_note}`} style={{ color: "#e5a94c" }}> ✎ порядок задан вручную</span>
            )}
          </div>
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {r.participants.map((p) => (
                <tr key={p.entry_id}>
                  <td style={tdStyle}>{p.callsign}</td>
                  <td style={tdStyle}>
                    {p.attempts_used == null ? "ещё не играл" : `${p.solved ? "угадал" : "не угадал"} за ${p.attempts_used}`}
                  </td>
                  {overridingRoundId === r.id && (
                    <td style={tdStyle}>
                      <input
                        type="number" min={1} value={ranks[p.entry_id] || ""}
                        onChange={(e) => setRanks((prev) => ({ ...prev, [p.entry_id]: e.target.value }))}
                        style={{ ...inputStyle, width: 50, padding: "2px 6px", fontSize: 12 }}
                        placeholder="Место"
                      />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {overridingRoundId === r.id ? (
            <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
              <input
                placeholder="Причина (обязательно)" value={orderNote}
                onChange={(e) => setOrderNote(e.target.value)}
                style={{ ...inputStyle, padding: "4px 8px", fontSize: 12, flex: 1 }}
              />
              <button
                onClick={() => handleSubmitOrder(r)}
                disabled={!orderNote.trim()}
                style={{ ...buttonStyle, padding: "4px 10px", fontSize: 12 }}
              >
                Сохранить порядок
              </button>
              <button onClick={() => setOverridingRoundId(null)} style={{ ...ghostButtonStyle, padding: "4px 10px", fontSize: 12 }}>Отмена</button>
            </div>
          ) : (
            <button onClick={() => startOverride(r)} style={{ ...ghostButtonStyle, padding: "4px 10px", fontSize: 12, marginTop: 8 }}>
              Задать порядок вручную
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
