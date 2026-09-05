import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import WordGrid from "../components/WordGrid.jsx";
import Keyboard from "../components/Keyboard.jsx";

const MAX_ATTEMPTS = 6;
const WORD_LENGTH = 5;

export default function PlayerGame() {
  const { token, tournamentId } = useParams();

  const [rows, setRows] = useState(
    Array.from({ length: MAX_ATTEMPTS }, () => ({ letters: null, statuses: null }))
  );
  const [currentGuess, setCurrentGuess] = useState("");
  const [activeRowIndex, setActiveRowIndex] = useState(0);
  const [letterStates, setLetterStates] = useState({});
  const [gameOver, setGameOver] = useState(false);
  const [message, setMessage] = useState("Загрузка...");
  const [callsign, setCallsign] = useState("");
  const [tournamentTitle, setTournamentTitle] = useState("");
  const [invalidLink, setInvalidLink] = useState(false);
  // "standard" — обычное слово дня (standard/championship/endless, тай-брейк тоже сюда же);
  // "bracket" — матч сетки на выбывание (championship после посева, knockout всегда)
  const [mode, setMode] = useState("standard");

  function fillPreviousGuesses(guesses) {
    if (!guesses?.length) return;
    setRows((prev) => {
      const next = [...prev];
      guesses.forEach((g, i) => {
        next[i] = { letters: g.split(""), statuses: null };
      });
      return next;
    });
  }

  useEffect(() => {
    async function load() {
      let standardData;
      try {
        const res = await fetch(`/api/game/today?token=${encodeURIComponent(token)}&tournament_id=${tournamentId}`);
        if (res.status === 404 || res.status === 403) {
          setInvalidLink(true);
          return;
        }
        standardData = await res.json();
      } catch (e) {
        setMessage("Не удалось загрузить статус игры.");
        return;
      }

      setCallsign(standardData.callsign || "");
      setTournamentTitle(standardData.tournament_title || "");

      if (standardData.has_word_today) {
        setMode("standard");
        if (standardData.already_played) {
          setMessage(standardData.solved ? "Вы уже угадали слово сегодня!" : "Попытки на сегодня исчерпаны.");
          setGameOver(true);
          fillPreviousGuesses(standardData.previous_guesses);
        } else {
          setMessage("");
        }
        return;
      }

      // не оказалось обычного слова дня — возможно, это розыгрыш на вылет
      // или championship уже в плей-офф: проверяем матч сетки
      let bracketData;
      try {
        const res = await fetch(`/api/game/bracket/today?token=${encodeURIComponent(token)}&tournament_id=${tournamentId}`);
        bracketData = await res.json();
      } catch (e) {
        setMessage("Не удалось загрузить статус игры.");
        return;
      }

      if (bracketData.callsign) setCallsign(bracketData.callsign);
      if (bracketData.tournament_title) setTournamentTitle(bracketData.tournament_title);

      if (!bracketData.has_match) {
        setMode("standard");
        setMessage("Слово дня сегодня недоступно — розыгрыш ещё не начался или уже завершён.");
        setGameOver(true);
        return;
      }

      setMode("bracket");
      const opponentNote = bracketData.opponent_callsign ? ` Соперник: ${bracketData.opponent_callsign}.` : "";

      if (bracketData.match_finished) {
        setGameOver(true);
        setMessage(
          (bracketData.won
            ? `Победа в раунде ${bracketData.round_number}!`
            : `Поражение в раунде ${bracketData.round_number}.`) + opponentNote
        );
        return;
      }

      if (bracketData.already_played) {
        setGameOver(true);
        setMessage(
          (bracketData.solved ? "Вы угадали слово этой игры." : "Попытки в этой игре исчерпаны.") +
            (bracketData.waiting_for_opponent ? " Ждём соперника." : "") +
            opponentNote
        );
        fillPreviousGuesses(bracketData.previous_guesses);
      } else {
        setMessage(`Матч сетки, раунд ${bracketData.round_number}.${opponentNote}`);
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
      setMessage(err.detail || "Слово не найдено в словаре.");
      return;
    }

    const data = await res.json();
    const statuses = data.result.map((r) => r.state);

    setRows((prev) => {
      const next = [...prev];
      next[activeRowIndex] = { letters: currentGuess.split(""), statuses };
      return next;
    });

    setLetterStates((prev) => {
      const next = { ...prev };
      data.result.forEach(({ letter, state }) => {
        const priority = { correct: 3, present: 2, absent: 1 };
        if (!next[letter] || priority[state] > priority[next[letter]]) {
          next[letter] = state;
        }
      });
      return next;
    });

    setCurrentGuess("");
    setActiveRowIndex((i) => i + 1);

    if (!data.game_over) {
      setMessage("");
      return;
    }

    setGameOver(true);
    if (mode === "bracket") {
      setMessage(
        data.solved
          ? "Угадано! Ждём, чем закончит соперник."
          : "Попытки в этой игре исчерпаны. Ждём соперника."
      );
    } else {
      setMessage(
        data.solved
          ? (data.points != null ? `Угадано! +${data.points} очков` : "Угадано!")
          : "Попытки исчерпаны. В следующий раз повезёт!"
      );
    }
  }

  if (invalidLink) {
    return (
      <Centered>
        <p>Эта ссылка недействительна, или вы не участвуете в этом розыгрыше.</p>
      </Centered>
    );
  }

  return (
    <Centered>
      <Link to={`/play/${token}`} style={{ color: "#818384", fontSize: 13, marginBottom: 8 }}>
        ← Мои розыгрыши
      </Link>
      {tournamentTitle && <h2 style={{ margin: "0 0 4px" }}>{tournamentTitle}</h2>}
      {callsign && <div style={{ opacity: 0.6, marginBottom: 8 }}>Игрок: {callsign}</div>}
      {message && <div style={{ marginBottom: 8, opacity: 0.8, textAlign: "center" }}>{message}</div>}
      <WordGrid rows={rows} currentGuess={currentGuess} activeRowIndex={activeRowIndex} />
      <Keyboard
        letterStates={letterStates}
        onLetter={handleLetter}
        onEnter={handleEnter}
        onBackspace={handleBackspace}
      />
    </Centered>
  );
}

function Centered({ children }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#121213",
        color: "#fff",
        fontFamily: "system-ui, sans-serif",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: 12,
      }}
    >
      {children}
    </div>
  );
}
