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
const PAD_V = 16;
const MIN_TILE = 32;
const MAX_TILE = 72;
const MAX_GRID_WIDTH = 400; // 5 клеток по MAX_TILE + зазоры — не растягивать шире и на просторном десктопе

function currentViewportHeight() {
  return window.visualViewport ? window.visualViewport.height : window.innerHeight;
}

/**
 * rows: массив по 6 строк, каждая — { letters: string[5], statuses: string[5] | null }
 * currentGuess: то, что игрок вводит прямо сейчас (для незавершённой строки)
 * animateRowIndex: индекс строки, которую только что отправили в этом сеансе —
 * для неё буквы переворачиваются по очереди, раскрывая цвет в середине переворота
 * (как на wordle.belousov.one); строки, уже пришедшие готовыми (при загрузке
 * страницы), просто показываются раскрашенными без анимации.
 * keyboardRef: ref на обёртку клавиатуры (см. PlayerGame.jsx) — нужен, чтобы
 * посчитать, сколько места она реально занимает внизу экрана.
 *
 * Размер клетки не фиксирован — подбирается напрямую из геометрии страницы:
 * высота видимой области (window.visualViewport, точнее отслеживает схлопывание
 * панелей мобильного браузера, чем innerHeight/CSS dvh) минус то, где поле
 * начинается (высота шапки над ним — определяется обычным потоком, без flex-grow)
 * минус высота клавиатуры. Полагаться на flex-grow внутри flex-колонки с
 * dvh-контейнером оказалось ненадёжно — в мобильном Safari эта комбинация вела
 * себя иначе, чем в десктопном браузере при разработке, и поле налезало на
 * клавиатуру (см. пункт бэклога) — явный расчёт в пикселях устраняет
 * зависимость от того, как конкретный браузер трактует эту комбинацию CSS.
 */
export default function WordGrid({ rows, currentGuess, activeRowIndex, animateRowIndex, keyboardRef }) {
  const containerRef = useRef(null);
  const [tileSize, setTileSize] = useState(56);
  // Довесок к нижнему отступу — выталкивает всё, что идёт после поля (то есть
  // клавиатуру), ровно к нижнему краю видимой области, без margin:auto/flex-grow
  // (см. пункт бэклога — в мобильном Safari эти приёмы в связке с dvh вели себя
  // непредсказуемо). Как только рядов+клеток+паддингов не хватает, чтобы самим
  // дотянуться до низа экрана, этот довесок выбирает ровно недостающее.
  const [bottomGap, setBottomGap] = useState(0);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    function recompute() {
      const rect = el.getBoundingClientRect();
      const keyboardHeight = keyboardRef?.current ? keyboardRef.current.getBoundingClientRect().height : 0;
      const availableHeight = Math.max(0, currentViewportHeight() - rect.top - keyboardHeight);

      const width = Math.min(rect.width, MAX_GRID_WIDTH);
      const usableHeight = Math.max(0, availableHeight - PAD_V * 2);
      const fromWidth = (width - GAP * 4) / 5;
      const fromHeight = (usableHeight - GAP * 5) / 6;
      const size = Math.max(MIN_TILE, Math.min(fromWidth, fromHeight, MAX_TILE));

      const contentHeight = size * 6 + GAP * 5 + PAD_V * 2;
      setTileSize(size);
      setBottomGap(Math.max(0, availableHeight - contentHeight));
    }

    recompute();

    const resizeObserver = new ResizeObserver(recompute);
    resizeObserver.observe(el);
    if (keyboardRef?.current) resizeObserver.observe(keyboardRef.current);

    const vv = window.visualViewport;
    if (vv) vv.addEventListener("resize", recompute);
    else window.addEventListener("resize", recompute);

    return () => {
      resizeObserver.disconnect();
      if (vv) vv.removeEventListener("resize", recompute);
      else window.removeEventListener("resize", recompute);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fontSize = Math.round(tileSize * 0.47);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: PAD_V,
        paddingBottom: PAD_V + bottomGap,
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
