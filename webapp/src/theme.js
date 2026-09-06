// Тема оформления для игровых страниц — задаётся админом глобально для всех
// игроков сразу (см. пункт бэклога про переключатель темы). Админ-панель
// темой не управляется, у неё всегда тёмное оформление.

export const THEMES = {
  dark: {
    bg: "#121213",
    fg: "#ffffff",
    bgSecondary: "#1c1c1e",
    border: "#3a3a3c",
    borderFilled: "#565758",
    correct: "#538d4e",
    present: "#b59f3b",
    absent: "#3a3a3c",
    keyDefault: "#818384",
    keyDefaultFg: "#ffffff",
    error: "#e5484d",
    muted: "#818384",
  },
  light: {
    bg: "#ffffff",
    fg: "#1a1a1b",
    bgSecondary: "#f6f6f6",
    border: "#d3d6da",
    borderFilled: "#878a8c",
    correct: "#6aaa64",
    present: "#c9b458",
    absent: "#787c7e",
    keyDefault: "#d3d6da",
    keyDefaultFg: "#1a1a1b",
    error: "#d7263d",
    muted: "#787c7e",
  },
};

export async function fetchTheme() {
  try {
    const r = await fetch("/api/game/theme");
    if (!r.ok) return "dark";
    const data = await r.json();
    return data.theme === "light" ? "light" : "dark";
  } catch (e) {
    return "dark";
  }
}

// CSS-переменные для установки на корневой контейнер страницы — дочерние
// инлайн-стили ссылаются на них через var(--name) и не знают о конкретной теме.
export function themeVars(theme) {
  const t = THEMES[theme] || THEMES.dark;
  return {
    "--bg": t.bg,
    "--fg": t.fg,
    "--bg-secondary": t.bgSecondary,
    "--border": t.border,
    "--border-filled": t.borderFilled,
    "--correct": t.correct,
    "--present": t.present,
    "--absent": t.absent,
    "--key-default": t.keyDefault,
    "--key-default-fg": t.keyDefaultFg,
    "--error": t.error,
    "--muted": t.muted,
  };
}
