import { useEffect, useState } from "react";
import { api, buttonStyle, ghostButtonStyle, inputStyle, panelStyle, tdStyle } from "../adminShared.jsx";

export function DictionaryPanel() {
  const [words, setWords] = useState([]);
  const [newWord, setNewWord] = useState("");
  const [error, setError] = useState("");

  const [addedWords, setAddedWords] = useState([]);
  const [newAddedWord, setNewAddedWord] = useState("");
  const [addedError, setAddedError] = useState("");
  const [exportStatus, setExportStatus] = useState("");

  async function refresh() {
    setWords(await api("/api/admin/dictionary/excluded"));
  }

  async function refreshAdded() {
    setAddedWords(await api("/api/admin/dictionary/added"));
  }

  useEffect(() => {
    refresh();
    refreshAdded();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleAdd(e) {
    e.preventDefault();
    setError("");
    try {
      await api("/api/admin/dictionary/excluded", {
        method: "POST",
        body: JSON.stringify({ word: newWord.trim().toLowerCase() }),
      });
      setNewWord("");
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handleRemove(id) {
    await api(`/api/admin/dictionary/excluded/${id}`, { method: "DELETE" });
    refresh();
  }

  async function handleAddMissing(e) {
    e.preventDefault();
    setAddedError("");
    try {
      await api("/api/admin/dictionary/added", {
        method: "POST",
        body: JSON.stringify({ word: newAddedWord.trim().toLowerCase() }),
      });
      setNewAddedWord("");
      refreshAdded();
    } catch (e) {
      setAddedError(e.message);
    }
  }

  async function handleRemoveAdded(id) {
    await api(`/api/admin/dictionary/added/${id}`, { method: "DELETE" });
    refreshAdded();
  }

  // Слова, добавленные через админку, живут только в базе данных. Экспорт — по
  // одному слову на строку, в формате api/data/answer_words_extra.txt: так их
  // можно сохранить в репозитории и не потерять при переезде на другую базу.
  const exportText = [...addedWords].map((w) => w.word).sort((a, b) => a.localeCompare(b, "ru")).join("\n") + "\n";

  async function handleCopyExport() {
    try {
      await navigator.clipboard.writeText(exportText);
      setExportStatus("Скопировано — вставьте в api/data/answer_words_extra.txt.");
    } catch (e) {
      setExportStatus("Браузер не дал скопировать — воспользуйтесь скачиванием.");
    }
    setTimeout(() => setExportStatus(""), 5000);
  }

  function handleDownloadExport() {
    const url = URL.createObjectURL(new Blob([exportText], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "added_words.txt";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <div style={{ ...panelStyle, maxWidth: 500, marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Словарь — добавить отсутствующее слово</h3>
        <p style={{ opacity: 0.7, fontSize: 13, marginTop: -4 }}>
          Если игрок ввёл существительное в именительном падеже из 5–7 букв, а
          игра его не приняла — добавьте его сюда. Сразу становится и валидной
          попыткой, и кандидатом на будущее слово дня, без деплоя.
        </p>
        <form onSubmit={handleAddMissing} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input
            placeholder="Слово из 5–7 букв"
            value={newAddedWord}
            onChange={(e) => setNewAddedWord(e.target.value)}
            maxLength={20}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button type="submit" style={buttonStyle}>Добавить</button>
        </form>
        {addedError && <div style={{ color: "#e5484d", marginBottom: 8 }}>{addedError}</div>}

        {addedWords.length > 0 && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
            <button
              onClick={handleCopyExport}
              title="Список слов для файла api/data/answer_words_extra.txt в репозитории — чтобы они не пропали при переезде на другую базу"
              style={ghostButtonStyle}
            >
              Скопировать список
            </button>
            <button onClick={handleDownloadExport} style={ghostButtonStyle}>Скачать .txt</button>
            {exportStatus && <span style={{ fontSize: 12, opacity: 0.7 }}>{exportStatus}</span>}
          </div>
        )}

        {addedWords.length === 0 ? (
          <div style={{ opacity: 0.5, fontSize: 13 }}>Список пуст.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {addedWords.map((w) => (
                <tr key={w.id} style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={{ ...tdStyle, textTransform: "uppercase", letterSpacing: 1 }}>{w.word}</td>
                  <td style={tdStyle}>
                    <button onClick={() => handleRemoveAdded(w.id)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                      Убрать
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div style={{ ...panelStyle, maxWidth: 500 }}>
        <h3 style={{ marginTop: 0 }}>Словарь — исключённые слова</h3>
        <p style={{ opacity: 0.7, fontSize: 13, marginTop: -4 }}>
          Слова из этого списка больше не будут предлагаться как новое слово дня —
          удобно вычищать странные/архаичные находки по факту игры. На уже
          назначенные слова (в т.ч. сегодняшнее) и на проверку вводимых попыток
          не влияет.
        </p>
        <form onSubmit={handleAdd} style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <input
            placeholder="Слово из 5–7 букв"
            value={newWord}
            onChange={(e) => setNewWord(e.target.value)}
            maxLength={20}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button type="submit" style={buttonStyle}>Исключить</button>
        </form>
        {error && <div style={{ color: "#e5484d", marginBottom: 8 }}>{error}</div>}

        {words.length === 0 ? (
          <div style={{ opacity: 0.5, fontSize: 13 }}>Список пуст.</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <tbody>
              {words.map((w) => (
                <tr key={w.id} style={{ borderTop: "1px solid #2a2a2c" }}>
                  <td style={{ ...tdStyle, textTransform: "uppercase", letterSpacing: 1 }}>{w.word}</td>
                  <td style={tdStyle}>
                    <button onClick={() => handleRemove(w.id)} style={{ ...ghostButtonStyle, fontSize: 12 }}>
                      Вернуть в словарь
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
