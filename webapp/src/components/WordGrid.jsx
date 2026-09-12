import { useLayoutEffect, useRef, useState } from "react";

const COLORS = {
  correct: "var(--correct)",
  present: "var(--present)",
  absent: "var(--absent)",
  empty: "var(--absent)",
};

const FLIP_DURATION_MS = 450;
const FLIP_STAGGER_MS = 300;
// Сколько всего идёт переворот всей строки из 5 букв — чтобы модалка с итогом
// (см. PlayerGame.jsx) не перекрывала грид раньше, чем доиграет анимация.
export const FLIP_TOTAL_MS = FLIP_DURATION_MS + FLIP_STAGGER_MS * 4;

const GAP = 8;
const PAD_V = 8;
const MIN_TILE = 32;
const MAX_TILE = 72;
const MAX_GRID_WIDTH = 400; // 5 клеток по MAX_TILE + зазоры — не растягивать шире и на просторном десктопе

/**
 * rows: массив по 6 строк, каждая — { letters: string[5], statuses: string[5] | null }
 * currentGuess: то, что игрок вводит прямо сейчас (для незавершённой строки)
 * animateRowIndex: индекс строки, которую только что отправили в этом сеансе —
 * для неё буквы переворачиваются по очереди, раскрывая цвет в середине переворота
 * (как на wordle.belousov.one); строки, уже пришедшие готовыми (при загрузке
 * страницы), просто показываются раскрашенными без анимации.
 *
 * Размер клетки не фиксирован — компонент занимает всё свободное место между
 * шапкой и клавиатурой (родитель — flex-колонка, см. PlayerGame.jsx) и сам
 * измеряет через ResizeObserver, сколько реально доступно по ширине/высоте,
 * подбирая максимальный размер клетки, при котором все 6 строк и 5 столбцов
 * ещё помещаются без обрезки — иначе клавиатура, прижатая к низу экрана
 * (см. пункт бэклога), оставляла бы пустой зазор над собой на высоких экранах.
 */
export default function WordGrid({ rows, currentGuess, activeRowIndex, animateRowIndex }) {
  const containerRef = useRef(null);
  const [tileSize, setTileSize] = useState(56);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function recompute() {
      const rect = el.getBoundingClientRect();
      const width = Math.min(rect.width, MAX_GRID_WIDTH);
      const height = Math.max(0, rect.height - PAD_V * 2);
      const fromWidth = (width - GAP * 4) / 5;
      const fromHeight = (height - GAP * 5) / 6;
      setTileSize(Math.max(MIN_TILE, Math.min(fromWidth, fromHeight, MAX_TILE)));
    }

    recompute();
    const observer = new ResizeObserver(recompute);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const fontSize = Math.round(tileSize * 0.47);

  return (
    <div
      ref={containerRef}
      style={{
        flex: "1 1 0",
        minHeight: 0,
        width: "100%",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: `${PAD_V}px 0`,
        boxSizing: "border-box",
      }}
    >
      <style>{`
        @keyframes wordgrid-flip {
          0%, 50% { background: transparent; border-color: var(--border-filled); color: var(--fg); }
          0% { transform: rotateX(0deg); }
          50% { transform: rotateX(90deg); }
          50.001%, 100% { background: var(--tile-bg); border-color: var(--tile-bg); color: #fff; }
          100% { transform: rotateX(0deg); }
        }
      `}</style>
      <div style={{ display: "grid", gap: GAP }}>
        {rows.map((row, i) => {
          const isActive = i === activeRowIndex;
          const statuses = row.statuses;
          const isAnimating = i === animateRowIndex && statuses;

          const letters = isActive
            ? (currentGuess + "     ").slice(0, 5).split("")
            : row.letters ?? Array(5).fill("");

          return (
            <div key={i} style={{ display: "flex", gap: GAP }}>
              {letters.map((letter, j) => {
                const filled = Boolean(letter.trim());
                const graded = statuses && !isAnimating;

                const style = isAnimating
                  ? {
                      "--tile-bg": COLORS[statuses[j]],
                      color: "var(--fg)",
                      background: "transparent",
                      border: "2px solid var(--border-filled)",
                      animation: `wordgrid-flip ${FLIP_DURATION_MS}ms ease-in-out ${j * FLIP_STAGGER_MS}ms both`,
                    }
                  : {
                      color: graded ? "#fff" : "var(--fg)",
                      background: graded ? COLORS[statuses[j]] : "transparent",
                      border: `2px solid ${graded ? COLORS[statuses[j]] : filled ? "var(--border-filled)" : "var(--border)"}`,
                    };

                return (
                  <div
                    key={j}
                    style={{
                      width: tileSize,
                      height: tileSize,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      borderRadius: 4,
                      ...style,
                    }}
                  >
                    {letter.trim()}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
