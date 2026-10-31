import { useState } from "react";
import { api, LengthSelect, isWordLength, inputStyle, buttonStyle, ghostButtonStyle } from "./adminShared.jsx";

// Единый набор действий над словом для всех режимов: подтвердить / другое слово / исключить из словаря /
// своё слово / длина. Панель передаёт только то, что у её слова есть: onConfirm — показывает «Подтвердить»,
// onReroll — «Другое слово» и «Исключить» (исключение из словаря + сразу другое слово), onReplace(слово) —
// «Своё слово», onLength(n) вместе с length — выбор длины. Обработчики могут быть асинхронными; ошибка
// показывается под кнопками. children — дополнительные кнопки в той же строке.
export default function WordActions({
  word, length, onLength, onReroll, onReplace, onConfirm, onExclude, compact, disabled, children,
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [custom, setCustom] = useState(null); // null — поле своего слова скрыто

  async function run(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const exclude = () => run(async () => {
    if (onExclude) {
      await onExclude();
      return;
    }
    await api("/api/admin/dictionary/excluded", { method: "POST", body: JSON.stringify({ word }) });
    await onReroll();
  });
  const replace = () => run(async () => {
    await onReplace(custom.trim().toLowerCase());
    setCustom(null);
  });

  const small = compact ? { padding: "2px 8px", fontSize: 11 } : {};
  const off = busy || disabled;
  return (
    <div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {onConfirm && (
          <button onClick={() => run(onConfirm)} disabled={off} style={{ ...buttonStyle, ...small }}>Подтвердить</button>
        )}
        {onLength && length != null && (
          <LengthSelect
            value={length} disabled={off} title="Сменить длину слова: система подберёт новое слово"
            onChange={(n) => { if (n != null && n !== length) run(() => onLength(n)); }}
          />
        )}
        {onReroll && (
          <button onClick={() => run(onReroll)} disabled={off} style={{ ...ghostButtonStyle, ...small }}>Другое слово</button>
        )}
        {onReroll && word && (
          <button
            onClick={exclude} disabled={off} style={{ ...ghostButtonStyle, ...small }}
            title="Исключить это слово из будущих предложений и сразу показать другое"
          >
            🚫 Исключить
          </button>
        )}
        {onReplace && (
          <button onClick={() => setCustom(custom === null ? "" : null)} disabled={off} style={{ ...ghostButtonStyle, ...small }}>
            Своё слово
          </button>
        )}
        {children}
      </div>
      {custom !== null && (
        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
          <input
            autoFocus value={custom} onChange={(e) => setCustom(e.target.value)} maxLength={7} placeholder="Слово 5–7 букв"
            onKeyDown={(e) => { if (e.key === "Enter" && isWordLength(custom)) replace(); }}
            style={{ ...inputStyle, flex: 1, minWidth: 0, maxWidth: 200, ...(compact ? { padding: "2px 6px", fontSize: 12 } : {}) }}
          />
          <button onClick={replace} disabled={off || !isWordLength(custom)} style={{ ...ghostButtonStyle, ...small }}>Заменить</button>
        </div>
      )}
      {error && <div style={{ color: "#e5484d", fontSize: 12, marginTop: 4 }}>{error}</div>}
    </div>
  );
}
