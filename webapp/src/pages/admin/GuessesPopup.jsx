import { useLayoutEffect, useRef, useState } from "react";

// Всплывающий список попыток над ячейкой — как у таблицы результатов стандартного
// режима (наведение на очки за день): попытки игрока по порядку. heading —
// необязательная строка сверху (слово, по которому сделаны попытки).
// Окно рисуется с position: fixed по координатам родительской ячейки: так его не обрезает
// прокручиваемая обёртка таблицы (overflow), как это было у верхних строк. Не помещается над
// ячейкой — показывается под ней; по горизонтали не выходит за край окна.
export function GuessesPopup({ guesses, heading }) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);

  useLayoutEffect(() => {
    const el = ref.current;
    const anchor = el ? el.parentElement : null;
    if (!el || !anchor) return undefined;
    function place() {
      const a = anchor.getBoundingClientRect();
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      const margin = 6;
      let top = a.top - h - margin;
      if (top < margin) top = a.bottom + margin;
      const left = Math.max(margin, Math.min(a.left + a.width / 2 - w / 2, window.innerWidth - w - margin));
      setPos({ top, left });
    }
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [guesses, heading]);

  return (
    <div
      ref={ref}
      style={{
        position: "fixed", top: pos ? pos.top : 0, left: pos ? pos.left : 0, visibility: pos ? "visible" : "hidden",
        background: "#1c1c1e", border: "1px solid #3a3a3c", borderRadius: 6, padding: "6px 10px",
        whiteSpace: "nowrap", zIndex: 50, textAlign: "left", pointerEvents: "none",
      }}
    >
      {heading && (
        <div style={{ fontSize: 11, opacity: 0.6, textTransform: "uppercase", letterSpacing: 1, marginBottom: 2 }}>{heading}</div>
      )}
      {guesses.map((g, gi) => (
        <div key={gi} style={{ fontFamily: "monospace", fontSize: 13, letterSpacing: 1, textTransform: "uppercase" }}>{g}</div>
      ))}
    </div>
  );
}
