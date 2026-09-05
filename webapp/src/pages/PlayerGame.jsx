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

  useEffect(() => {
    fetch(`/api/game/today?token=${encodeURIComponent(token)}&tournament_id=${tournamentId}`)
      .then((r) => {
        if (r.status === 404 || r.status === 403) {
          setInvalidLink(true);
          throw new Error("invalid link");
        }
        return r.json();
      })
      .then((data) => {
        setCallsign(data.callsign || "");
        setTournamentTitle(data.tournament_title || "");
        if (!data.has_word_today) {
          setMessage("Слово дня сегодня недоступно — розыгрыш ещё не начался или уже завершён.");
          setGameOver(true);
        } else if (data.already_played) {
          setMessage(data.solved ? "Вы уже угадали слово сегодня!" : "Попытки на сегодня исчерпаны.");
          setGameOver(true);
          if (data.previous_guesses?.length) {
            setRows((prev) => {
              const next = [...prev];
              data.previous_guesses.forEach((g, i) => {
                next[i] = { letters: g.split(""), statuses: null };
              });
              return next;
            });
          }
        } else {
          setMessage("");
        }
      })
      .catch(() => {
        if (!invalidLink) setMessage("Не удалось загрузить статус игры.");
      });
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

    const res = await fetch("/api/game/guess", {
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
    setMessage("");

    if (data.game_over) {
      setGameOver(true);
      setMessage(
        data.solved
          ? `Угадано! +${data.points} очков`
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
