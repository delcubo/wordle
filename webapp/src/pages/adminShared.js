// Общее для страниц админки: запросы к API, стили, хук ширины экрана. Вынесено из AdminDashboard.jsx,
// чтобы новые экраны (например «Сегодня») можно было держать в отдельных файлах.
import { useEffect, useState } from "react";
import { ADMIN_BASE } from "../adminBase.js";

export const TYPE_LABEL = {
  standard: "Стандартный", knockout: "На вылет", championship: "Чемпионат", endless: "Бессрочная игра", tiebreak: "Тай-брейк", marathon: "Марафон",
};

export async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 401) {
    window.location.href = ADMIN_BASE;
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Ошибка запроса");
  }
  return res.json();
}

export function useIsMobile(breakpoint = 640) {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < breakpoint);
  useEffect(() => {
    function onResize() {
      setIsMobile(window.innerWidth < breakpoint);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [breakpoint]);
  return isMobile;
}

export const panelStyle = { background: "#1c1c1e", borderRadius: 10, padding: 16 };
// colorScheme: "dark" — иначе нативная иконка календаря/цвета у <input type="date">
// рисуется тёмной по умолчанию и сливается с тёмным фоном поля (см. пункт бэклога).
export const inputStyle = { padding: "8px 10px", borderRadius: 6, border: "1px solid #3a3a3c", background: "#121213", color: "#fff", fontSize: 14, colorScheme: "dark" };
export const buttonStyle = { padding: "8px 12px", borderRadius: 6, border: "none", background: "#538d4e", color: "#fff", fontSize: 14, cursor: "pointer" };
export const ghostButtonStyle = { padding: "6px 10px", borderRadius: 6, border: "1px solid #3a3a3c", background: "transparent", color: "#fff", fontSize: 13, cursor: "pointer" };
export const thStyle = { padding: "4px 8px", textAlign: "left" };
export const tdStyle = { padding: "4px 8px" };
