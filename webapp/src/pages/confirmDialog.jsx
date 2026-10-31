import { useEffect, useState } from "react";
import { buttonStyle, ghostButtonStyle } from "./adminShared.jsx";

// Единый диалог подтверждения вместо системного window.confirm: askConfirm(...) возвращает промис с
// true/false. Достаточно передать прежний текст вопроса — заголовок (первое предложение вопроса),
// пояснение (остальное: что произойдёт) и подпись кнопки (глагол из начала вопроса) выводятся сами;
// всё это можно задать явно в options. ConfirmHost должен быть один раз выведен на странице.
const DANGER_VERBS = ["Удалить", "Сбросить", "Отключить", "Выдать", "Переместить"];
let show = null;

export function parseConfirmMessage(message) {
  const text = String(message).trim();
  const cut = text.search(/\?(\s|$)/);
  const title = cut === -1 ? text : text.slice(0, cut + 1);
  const body = cut === -1 ? "" : text.slice(cut + 1).trim();
  const verb = title.split(/\s+/)[0] || "Подтвердить";
  return { title, body, confirmLabel: verb, danger: DANGER_VERBS.includes(verb) };
}

export function askConfirm(message, options = {}) {
  if (!show) return Promise.resolve(window.confirm(message)); // запасной путь, если ConfirmHost не выведен
  return new Promise((resolve) => show({ ...parseConfirmMessage(message), ...options, resolve }));
}

export function ConfirmHost() {
  const [dialog, setDialog] = useState(null);

  useEffect(() => {
    show = setDialog;
    return () => { show = null; };
  }, []);

  useEffect(() => {
    if (!dialog) return undefined;
    function onKey(e) {
      if (e.key === "Escape") close(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dialog]);

  function close(result) {
    dialog.resolve(result);
    setDialog(null);
  }

  if (!dialog) return null;
  return (
    <div
      onClick={() => close(false)}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
    >
      <div
        role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}
        style={{ background: "#1c1c1e", border: "1px solid #3a3a3c", borderRadius: 10, padding: 18, width: "100%", maxWidth: 420, color: "#fff" }}
      >
        <div style={{ fontSize: 16, fontWeight: 700, whiteSpace: "pre-line", overflowWrap: "anywhere" }}>{dialog.title}</div>
        {dialog.body && (
          <div style={{ fontSize: 14, opacity: 0.8, marginTop: 8, whiteSpace: "pre-line", overflowWrap: "anywhere" }}>{dialog.body}</div>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16, flexWrap: "wrap" }}>
          <button autoFocus onClick={() => close(false)} style={ghostButtonStyle}>Отмена</button>
          <button
            onClick={() => close(true)}
            style={{ ...buttonStyle, background: dialog.danger ? "#c0392b" : buttonStyle.background }}
          >
            {dialog.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
