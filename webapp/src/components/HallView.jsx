import { useEffect, useState } from "react";
import "./hall.css";

const KINDS = [
  { key: "table", field: "table_image_id", icon: "▦", label: "Таблица турнира", cls: "" },
  { key: "bracket", field: "bracket_image_id", icon: "⑂", label: "Сетка турнира", cls: "" },
  { key: "certificate", field: "certificate_image_id", icon: "♙", label: "Сертификат победителя", cls: " certificate" },
];

function formatDate(iso) {
  const [y, m, d] = iso.split("-");
  return { d, m, y };
}

// "07.04 – 04.05.2027", а если турнир пересёк границу года — с годом у обеих дат
export function formatDateRange(start, end) {
  const s = formatDate(start);
  const e = formatDate(end);
  if (s.y === e.y) return `${s.d}.${s.m} – ${e.d}.${e.m}.${e.y}`;
  return `${s.d}.${s.m}.${s.y} – ${e.d}.${e.m}.${e.y}`;
}

// Последнее слово названия — римская цифра: подсвечивается жёлтым, как в макете
function Title({ title }) {
  const parts = title.trim().split(/\s+/);
  const last = parts[parts.length - 1];
  if (parts.length > 1 && /^[IVXLCDM]+$/.test(last)) {
    return (
      <>
        {parts.slice(0, -1).join(" ")} <span className="hall-roman">{last}</span>
      </>
    );
  }
  return <>{title}</>;
}

function Actions({ entry, onOpen }) {
  return (
    <div className="hall-actions">
      {KINDS.map((k) => {
        const imageId = entry[k.field];
        return (
          <button
            key={k.key}
            className={`hall-action${k.cls}`}
            disabled={!imageId}
            title={imageId ? undefined : "Пока не добавлено"}
            onClick={() => onOpen(entry, k, imageId)}
          >
            <span className="hall-action-icon">{k.icon}</span>
            <span className="hall-action-text">{k.label}</span>
            <span className="hall-arrow">›</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Страница зала славы (макет — wordle_kombat_public_page). Один и тот же
 * компонент показывает её и игроку, и админу в предпросмотре — различается
 * только imageUrl(id): у игрока картинка отдаётся по его токену, у админа —
 * по админской сессии.
 *  - entries: записи от новых к старым, у одной is_current = true
 *  - imageUrl: id картинки -> адрес
 *  - back: необязательный элемент "назад" над шапкой
 */
export default function HallView({ entries, imageUrl, back }) {
  const [opened, setOpened] = useState(null); // {entry, kind, imageId}

  useEffect(() => {
    if (!opened) return undefined;
    function onKey(e) {
      if (e.key === "Escape") setOpened(null);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [opened]);

  const current = entries.find((e) => e.is_current) || null;
  const archive = entries.filter((e) => !current || e.id !== current.id);

  function open(entry, kind, imageId) {
    setOpened({ entry, kind, imageId });
  }

  return (
    <div className="hall-page">
      <div className="hall-wrap">{back}</div>
      <header className="hall-hero hall-wrap">
        <div className="hall-eyebrow">Зал славы</div>
        <img className="hall-logo" src="/hall-logo.webp" alt="Вордл Комбат — 5 букв. 6 попыток. 1 победитель." />
        <h1 className="hall-section-title">Хроника чемпионов</h1>
        <p className="hall-subtitle">История турниров. История побед.</p>
      </header>

      <main className="hall-wrap">
        {entries.length === 0 && <div className="hall-empty">Здесь появятся чемпионы прошедших турниров.</div>}

        {current && (
          <section className="hall-champion">
            <div className="hall-champion-main">
              <div className="hall-tag"><span className="hall-crown">♛</span> Действующий чемпион</div>
              <h2 className="hall-tournament-name"><Title title={current.title} /></h2>
              <div className="hall-dates">{formatDateRange(current.date_start, current.date_end)}</div>
              <div className="hall-winner-label">Чемпион</div>
              <p className="hall-winner">{current.champion}</p>
            </div>
            <Actions entry={current} onOpen={open} />
          </section>
        )}

        {archive.length > 0 && (
          <section className="hall-archive">
            <div className="hall-archive-head">
              <div className="hall-trophy" aria-hidden="true">🏆</div>
              <div>
                <h2>Летопись турниров</h2>
                <p>Каждый чемпион остаётся в истории.</p>
              </div>
            </div>
            <div className="hall-archive-list">
              {archive.map((e) => (
                <article className="hall-tournament" key={e.id}>
                  <div className="hall-tournament-info">
                    <h3><Title title={e.title} /></h3>
                    <div className="hall-dates">{formatDateRange(e.date_start, e.date_end)}</div>
                    <div className="hall-winner-label">Чемпион</div>
                    <p className="hall-winner">{e.champion}</p>
                  </div>
                  <Actions entry={e} onOpen={open} />
                </article>
              ))}
            </div>
          </section>
        )}
      </main>

      <footer className="hall-foot hall-wrap">Вордл Комбат <span>·</span> Зал славы</footer>

      {opened && (
        <div className="hall-modal" role="dialog" aria-modal="true" onClick={(e) => { if (e.target === e.currentTarget) setOpened(null); }}>
          <div className="hall-modal-card">
            <div className="hall-modal-top">
              <div>
                <h2>{opened.kind.label}</h2>
                <div className="hall-modal-note">{opened.entry.title}</div>
              </div>
              <button className="hall-close" onClick={() => setOpened(null)} aria-label="Закрыть">✕</button>
            </div>
            <div className="hall-modal-img">
              <img src={imageUrl(opened.imageId)} alt={`${opened.kind.label} — ${opened.entry.title}`} />
            </div>
            <a className="hall-modal-link" href={imageUrl(opened.imageId)} target="_blank" rel="noopener noreferrer">
              Открыть в новой вкладке ↗
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
