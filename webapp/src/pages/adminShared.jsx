// Общее для страниц админки: запросы к API, стили, хук ширины экрана. Вынесено из AdminDashboard.jsx,
// чтобы новые экраны (например «Сегодня») можно было держать в отдельных файлах.
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { ADMIN_BASE } from "../adminBase.js";

export const LENGTHS = [5, 6, 7];
export const isWordLength = (w) => LENGTHS.includes((w || "").trim().length);

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

// Выбор длины слова (5/6/7); пустое значение — «как базовая» (если задан allowEmpty).
export function LengthSelect({ value, onChange, disabled, allowEmpty, emptyLabel = "—", title, style }) {
  return (
    <select
      value={value ?? ""} disabled={disabled} title={title}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      style={{ ...inputStyle, padding: "2px 4px", fontSize: 12, width: "auto", ...style }}
    >
      {allowEmpty && <option value="">{emptyLabel}</option>}
      {LENGTHS.map((n) => <option key={n} value={n}>{n} букв</option>)}
    </select>
  );
}

// Реестр режимов (GET /api/admin/modes, см. api/modes.py): название, описание и модули каждого режима.
// Админка строит по нему мастер создания, форму настроек, подвкладки и панели.
export function modeHelpers(list) {
  const byType = Object.fromEntries((list || []).map((m) => [m.type, m]));
  return {
    list: list || [],
    byType,
    has: (type, module) => !!byType[type] && byType[type].modules.includes(module),
    label: (type) => (byType[type] && byType[type].label) || TYPE_LABEL[type] || type,
  };
}

export const ModesContext = createContext(modeHelpers([]));
export const useModes = () => useContext(ModesContext);

// Всегда актуальное значение для отбрасывания устаревших ответов — если
// админ успел переключиться на другой розыгрыш/матч, пока запрос летал,
// применять его результат уже нельзя (иначе на экране повиснут данные не
// того розыгрыша под правильным заголовком). См. refresh() в панелях ниже.
export function useLatest(value) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

export const STATUS_LABEL = { draft: "черновик", active: "идёт", tiebreak: "тай-брейк", playoff: "плей-офф", finished: "завершён" };

export function userLabel(u) {
  return u.admin_note || `Игрок #${u.id}`;
}
