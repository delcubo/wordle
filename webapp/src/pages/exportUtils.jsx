import { useState } from "react";
import { ghostButtonStyle } from "./adminShared.jsx";

// Общее для экспорта таблиц результатов: имя файла, скачивание картинки с canvas и кнопка копирования текста
// с подтверждением «Скопировано!». Сама отрисовка таблицы у каждой панели своя — общим стал только вывод.
export function safeFileName(title, suffix = "") {
  return `${String(title).replace(/[^\p{L}\p{N}]+/gu, "_")}${suffix}.png`;
}

// Скачивает canvas как PNG. suffix — например "_тайбрейк" (после названия розыгрыша).
export function downloadCanvas(canvas, title, suffix = "") {
  canvas.toBlob((blob) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = safeFileName(title, suffix);
    a.click();
    URL.revokeObjectURL(url);
  });
}

// getText() возвращает текст для вставки в чат. На время подтверждения кнопка меняет подпись.
export function CopyButton({ getText, label = "Скопировать таблицу" }) {
  const [copied, setCopied] = useState(false);

  async function handleClick() {
    try {
      await navigator.clipboard.writeText(getText());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      setCopied(false);
    }
  }

  return <button onClick={handleClick} style={ghostButtonStyle}>{copied ? "Скопировано!" : label}</button>;
}
