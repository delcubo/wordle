import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import WordGrid, { FLIP_TOTAL_MS } from "../components/WordGrid.jsx";
import Keyboard from "../components/Keyboard.jsx";
import ResultModal from "../components/ResultModal.jsx";
import { fetchTheme, themeVars } from "../theme.js";

const MAX_ATTEMPTS = 6;
const WORD_LENGTH = 5;
const LETTER_PRIORITY = { correct: 3, present: 2, absent: 1 };

function buildRows(guesses, results) {
  const rows = Array.from({ length: MAX_ATTEMPTS }, () => ({ letters: null, statuses: null }));
  (guesses || []).forEach((g, i) => {
    rows[i] = { letters: g.split(""), statuses: (results && results[i]) || null };
  });
  return rows;
}

function buildLetterStates(guesses, results) {
  const map = {};
  (guesses || []).forEach((guess, i) => {
    const statuses = (results && results[i]) || [];
    guess.split("").forEach((letter, j) => {
      const state = statuses[j];
      if (!state) return;
      if (!map[letter] || LETTER_PRIORITY[state] > LETTER_PRIORITY[map[letter]]) map[letter] = state;
    });
  });
  return map;
}

export default function PlayerGame() {
  const { token, tournamentId } = useParams();

  const [rows, setRows] = useState(buildRows([], []));
  const [currentGuess, setCurrentGuess] = useState("");
  const [activeRowIndex, setActiveRowIndex] = useState(0);
  const [letterStates, setLetterStates] = useState({});
  const [gameOver, setGameOver] = useState(false);
  const [message, setMessage] = useState("Загрузка...");
  const [isError, setIsError] = useState(false);
  const [callsign, setCallsign] = useState("");
  const [tournamentTitle, setTournamentTitle] = useState("");
  const [hashtag, setHashtag] = useState(null);
  const [invalidLink, setInvalidLink] = useState(false);
  // "standard" — обычное слово дня (standard/championship/endless, тай-брейк тоже сюда же);
  // "bracket" — матч сетки на выбывание (championship после посева, knockout всегда)
  const [mode, setMode] = useState("standard");
  const [modal, setModal] = useState(null);
  const [theme, setTheme] = useState("dark");
  const [animateRowIndex, setAnimateRowIndex] = useState(null);
  const errorTimeoutRef = useRef(null);
  const keyboardWrapRef = useRef(null);

  useEffect(() => {
    fetchTheme().then(setTheme);
  }, []);

  // Ошибка ввода (например "слова нет в словаре") гаснет сама через пару
  // секунд — иначе если она уже висит и игрок снова вводит несуществующее
  // слово, ему не видно, что это новое отклонение, а не старое сообщение.
  function showTransientError(text) {
    setMessage(text);
    setIsError(true);
    if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
    errorTimeoutRef.current = setTimeout(() => {
      setMessage("");
      setIsError(false);
      errorTimeoutRef.current = null;
    }, 2500);
  }

  useEffect(() => () => {
    if (errorTimeoutRef.current) clearTimeout(errorTimeoutRef.current);
  }, []);

  function applyStandardStatus(data) {
    setCallsign(data.callsign || "");
    setTournamentTitle(data.tournament_title || "");
    setHashtag(data.hashtag || null);

    if (!data.has_word_today) {
      setGameOver(true);
      setMessage(
        data.paused
          ? "Розыгрыш временно приостановлен админом."
          : "Слово дня сегодня недоступно — розыгрыш ещё не начался или уже завершён."
      );
      setIsError(false);
      return;
    }

    const finished = data.already_played;
    setRows(buildRows(data.previous_guesses, data.previous_results));
    setLetterStates(buildLetterStates(data.previous_guesses, data.previous_results));
    setActiveRowIndex(finished ? -1 : (data.previous_guesses || []).length);
    setGameOver(finished);
    setIsError(false);

    if (finished) {
      setMessage(data.solved ? "Вы уже угадали слово сегодня!" : "Попытки на сегодня исчерпаны.");
      setModal({
        title: data.tournament_title,
        callsign: data.callsign,
        hashtag: data.hashtag,
        attemptsUsed: data.attempts_used,
        solved: data.solved,
        grid: data.previous_results,
        answerWord: data.answer_word,
        countdownTarget: data.next_word_at,
      });
    } else {
      setMessage("");
      setModal(null);
    }
  }

  function applyBracketStatus(data, { announceTie } = {}) {
    setCallsign(data.callsign || "");
    setTournamentTitle(data.tournament_title || "");
    setHashtag(data.hashtag || null);

    if (!data.has_match) {
      setGameOver(true);
      setMessage(
        data.paused
          ? "Розыгрыш временно приостановлен админом."
          : "Слово дня сегодня недоступно — розыгрыш ещё не начался или уже завершён."
      );
      setIsError(false);
      return;
    }

    const finished = data.already_played || data.match_finished;
    setRows(buildRows(data.previous_guesses, data.previous_results));
    setLetterStates(buildLetterStates(data.previous_guesses, data.previous_results));
    setActiveRowIndex(finished ? -1 : (data.previous_guesses || []).length);
    setGameOver(finished);
    setIsError(false);

    const opponentNote = data.opponent_callsign ? ` Соперник: ${data.opponent_callsign}.` : "";

    if (data.match_finished) {
      const oppResult = data.opponent_attempts_used == null
        ? ""
        : ` Соперник ${data.opponent_solved ? "угадал" : "не угадал"} за ${data.opponent_attempts_used}/6.`;
      setMessage((data.won ? `Победа в раунде ${data.round_number}!` : `Поражение в раунде ${data.round_number}.`) + opponentNote);
      if (!announceTie) {
        setModal({
          title: data.tournament_title,
          callsign: data.callsign,
          hashtag: data.hashtag,
          attemptsUsed: data.attempts_used,
          solved: data.solved,
          grid: data.previous_results,
          answerWord: data.answer_word,
          message: (data.won ? "Победа!" : "Поражение.") + oppResult,
          countdownTarget: data.won ? data.next_word_at : null,
          gameEnded: !data.won,
        });
      }
      return;
    }

    if (data.already_played) {
      setMessage(
        (data.solved ? "Вы угадали слово этой игры." : "Попытки в этой игре исчерпаны.") +
          " Ждём соперника." + opponentNote
      );
      if (!announceTie) {
        setModal({
          title: data.tournament_title,
          callsign: data.callsign,
          hashtag: data.hashtag,
          attemptsUsed: data.attempts_used,
          solved: data.solved,
          grid: data.previous_results,
          message: "Вы сыграли, ждём соперника." + opponentNote,
        });
      }
    } else {
      setMessage(
        `Матч сетки, раунд ${data.round_number}${data.is_sudden_death ? " (доп. раунд после ничьей)" : ""}.${opponentNote}`
      );
      if (!announceTie) setModal(null);
    }
  }

  async function fetchStandardStatus() {
    const res = await fetch(`/api/game/today?token=${encodeURIComponent(token)}&tournament_id=${tournamentId}`);
    if (res.status === 404 || res.status === 403) {
      setInvalidLink(true);
      return null;
    }
    return res.json();
  }

  async function fetchBracketStatus() {
    const res = await fetch(`/api/game/bracket/today?token=${encodeURIComponent(token)}&tournament_id=${tournamentId}`);
    return res.json();
  }

  useEffect(() => {
    async function load() {
      try {
        const standardData = await fetchStandardStatus();
        if (standardData === null) return; // invalidLink уже выставлен

        if (standardData.has_word_today) {
          setMode("standard");
          applyStandardStatus(standardData);
          return;
        }

        // нет обычного слова дня — возможно, это розыгрыш на вылет
        // или championship уже в плей-офф: проверяем матч сетки
        const bracketData = await fetchBracketStatus();
        if (bracketData.has_match) {
          setMode("bracket");
          applyBracketStatus(bracketData);
        } else {
          setMode("standard");
          applyStandardStatus(standardData);
        }
      } catch (e) {
        setMessage("Не удалось загрузить статус игры.");
        setIsError(true);
      }
    }

    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, tournamentId]);

  function handleLetter(letter) {
    if (gameOver || currentGuess.length >= WORD_LENGTH) return;
    setCurrentGuess((g) => g + letter);
  }

  function handleBackspace() {
    setCurrentGuess((g) => g.slice(0, -1));
  }

  async function handleEnter() {
    if (currentGuess.length !== WORD_LENGTH || gameOver) return;

    const endpoint = mode === "bracket" ? "/api/game/bracket/guess" : "/api/game/guess";
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, tournament_id: Number(tournamentId), guess: currentGuess }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showTransientError(err.detail || "Слово не найдено в словаре.");
      return;
    }

    if (errorTimeoutRef.current) {
      clearTimeout(errorTimeoutRef.current);
      errorTimeoutRef.current = null;
    }

    const data = await res.json();
    const statuses = data.result.map((r) => r.state);

    // грид "этого раунда" на момент прямо сейчас — до любых дальнейших фетчей,
    // пригодится, если матч сетки уйдёт в sudden death (там прошлый раунд уже
    // не будет виден в свежем статусе — там будет уже новый, пустой)
    const roundGrid = [...rows.slice(0, activeRowIndex).map((r) => r.statuses), statuses];

    setRows((prev) => {
      const next = [...prev];
      next[activeRowIndex] = { letters: currentGuess.split(""), statuses };
      return next;
    });
    setAnimateRowIndex(activeRowIndex);
    setLetterStates((prev) => {
      const next = { ...prev };
      data.result.forEach(({ letter, state }) => {
        if (!next[letter] || LETTER_PRIORITY[state] > LETTER_PRIORITY[next[letter]]) next[letter] = state;
      });
      return next;
    });
    setCurrentGuess("");
    setActiveRowIndex((i) => i + 1);
    setIsError(false);

    if (!data.game_over) {
      setMessage("");
      return;
    }

    setGameOver(true);

    // Итоговую модалку и любые UI-обновления, перекрывающие грид, откладываем
    // до конца анимации переворота последней строки — иначе она перекроет
    // грид раньше, чем игрок увидит цвет своей последней попытки.
    if (mode === "bracket") {
      const fresh = await fetchBracketStatus();
      const isTie = !fresh.match_finished && !fresh.already_played;
      setTimeout(() => {
        if (isTie) {
          setModal({
            title: fresh.tournament_title,
            callsign: fresh.callsign,
            hashtag: fresh.hashtag,
            attemptsUsed: data.attempts_used,
            solved: data.solved,
            grid: roundGrid,
            message: "Ничья! У соперника такой же результат — начинается дополнительный раунд (sudden death).",
          });
        }
        applyBracketStatus(fresh, { announceTie: isTie });
      }, FLIP_TOTAL_MS);
      return;
    }

    const fresh = await fetchStandardStatus();
    setTimeout(() => {
      if (fresh) applyStandardStatus(fresh);
    }, FLIP_TOTAL_MS);
  }

  if (invalidLink) {
    return (
      <Centered theme={theme}>
        <p>Эта ссылка недействительна, или вы не участвуете в этом розыгрыше.</p>
      </Centered>
    );
  }

  return (
    <Centered theme={theme}>
      <Link to={`/play/${token}`} style={{ color: "var(--muted)", fontSize: 13, marginBottom: 8 }}>
        ← Мои розыгрыши
      </Link>
      {tournamentTitle && <h2 style={{ margin: "0 0 4px" }}>{tournamentTitle}</h2>}
      {callsign && <div style={{ opacity: 0.6, marginBottom: 8 }}>Игрок: {callsign}</div>}
      {message && (
        <div style={{ marginBottom: 8, opacity: isError ? 1 : 0.8, textAlign: "center", color: isError ? "var(--error)" : "var(--fg)" }}>
          {message}
        </div>
      )}
      <WordGrid rows={rows} currentGuess={currentGuess} activeRowIndex={activeRowIndex} animateRowIndex={animateRowIndex} keyboardRef={keyboardWrapRef} />
      <div ref={keyboardWrapRef} style={{ width: "100%" }}>
        <Keyboard
          letterStates={letterStates}
          onLetter={handleLetter}
          onEnter={handleEnter}
          onBackspace={handleBackspace}
        />
      </div>
      {modal && (
        <ResultModal
          title={modal.title}
          callsign={modal.callsign ?? callsign}
          hashtag={modal.hashtag !== undefined ? modal.hashtag : hashtag}
          attemptsUsed={modal.attemptsUsed}
          solved={modal.solved}
          grid={modal.grid}
          answerWord={modal.answerWord}
          message={modal.message}
          countdownTarget={modal.countdownTarget}
          gameEnded={modal.gameEnded}
          onClose={() => setModal(null)}
        />
      )}
    </Centered>
  );
}

function Centered({ children, theme = "dark" }) {
  // dvh в связке с flex:1-детьми (см. WordGrid.jsx) ведёт себя не одинаково
  // во всех браузерах — в мобильном Safari при открытых панелях адресной
  // строки/навигации измерение "доступной высоты" через CSS-юнит оказалось
  // ненадёжным (см. пункт бэклога: поле налезало на клавиатуру). Меряем
  // реальную видимую высоту напрямую через JS (visualViewport, если есть —
  // он точнее отслеживает схлопывание панелей браузера, чем innerHeight) и
  // используем как min-height в пикселях — однозначное число, а не единица,
  // чью трактовку внутри flex-контейнера браузеры могут расходиться.
  const [viewportHeight, setViewportHeight] = useState(null);

  useLayoutEffect(() => {
    function measure() {
      const vv = window.visualViewport;
      setViewportHeight(vv ? vv.height : window.innerHeight);
    }
    measure();
    const vv = window.visualViewport;
    if (vv) {
      vv.addEventListener("resize", measure);
      return () => vv.removeEventListener("resize", measure);
    }
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return (
    <div
      style={{
        ...themeVars(theme),
        minHeight: viewportHeight != null ? `${viewportHeight}px` : "100dvh",
        background: "var(--bg)",
        color: "var(--fg)",
        fontFamily: "system-ui, sans-serif",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "12px 8px 0",
        boxSizing: "border-box",
        width: "100%",
      }}
    >
      {children}
    </div>
  );
}
