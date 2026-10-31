import { useState } from "react";
import { api, useModes, LENGTHS, inputStyle, buttonStyle, ghostButtonStyle } from "./adminShared.jsx";

// Создание и настройки розыгрыша строятся из одного каталога полей (FIELDS) и реестра режимов
// (api/modes.py): поле показывается, если у режима есть его модуль. Новая настройка — одна запись
// в каталоге плюс модуль в реестре; проверок «if type === …» в формах нет.

export const DEFAULT_SCORING = { "1": 10, "2": 5, "3": 4, "4": 3, "5": 2, "6": 1 };

// В какие дни откроются бонусные слова при длительности D и N (для подсказок)
export const bonusDays = (duration, every) => {
  const d = Number(duration);
  const n = Number(every);
  if (!d || !n || n < 1) return [];
  return Array.from({ length: Math.floor(d / n) }, (_, i) => (i + 1) * n);
};

const GROUPS = [
  { key: "base", label: "Основное" },
  { key: "words", label: "Слова" },
  { key: "format", label: "Сроки и формат" },
  { key: "extras", label: "Команды и бонусы" },
  { key: "notify", label: "Уведомления" },
];

const TEAMS_LABEL = { marathon: "Командный зачёт", tiebreak: "Командный тай-брейк" };
const TEAMS_HINT = {
  marathon: "Админ собирает игроков в команды (от 2 человек); место команды — по среднему числу попыток на слово. "
    + "Игра для участников не меняется, в копируемый результат добавляется название команды.",
  tiebreak: "Места разыгрывают команды (от 2 подключённых игроков): у каждого игрока в раунде своё слово, результат "
    + "команды — среднее число попыток (не угадал — 7, не завершил или не играл — 8). Включить и собрать команды нужно до "
    + "начала: после старта менять нельзя.",
};
const END_DATE_LABEL = {
  marathon: { create: "Дата окончания (необязательно: без неё игра идёт, пока вы её не закроете)", edit: "Дата окончания (пусто — без срока)" },
  tiebreak: {
    create: "Дата окончания (необязательно: без неё раунд закрывается в конце дня старта)",
    edit: "Дата окончания (пусто — раунд закрывается в конце дня, в который он начался)",
  },
};
const BRACKET_HINT = {
  championship: "Сколько лучших выходят в плей-офф (степень двойки).",
  knockout: "Общий размер сетки (степень двойки).",
};

// ctx = { mode: "create" | "edit", type, tournament, values, todayIso, has }
//   module — поле нужно только режимам с этим модулем; createOnly / editOnly — где поле показывается;
//   show(ctx) — дополнительное условие; hint(ctx) / warn(ctx) — пояснение и предупреждение.
const FIELDS = [
  { key: "title", group: "base", kind: "text", label: "Название", placeholder: "День/стадия добавляются автоматически", required: true },
  {
    key: "start_date", group: "base", kind: "date", label: "Дата старта", required: true,
    show: (c) => c.mode === "create" || c.tournament.start_date >= c.todayIso,
    min: (c) => (c.mode === "edit" ? c.todayIso : undefined),
    hint: (c) => (c.mode === "edit" ? "Розыгрыш ещё не начался — дату можно изменить." : null),
  },
  { key: "hashtag", group: "base", kind: "text", label: "Хэштег для результата", placeholder: "например #вордли" },
  { key: "note", group: "base", kind: "textarea", label: "Заметка админа", placeholder: "Описание — игрокам не видна" },

  {
    key: "word_length", group: "words", kind: "length", label: "Длина слов", createOnly: true,
    hint: (c) => (["marathon_words", "playoff", "tiebreak_words"].some(c.has) ? "Базовая длина — по позициям её можно будет менять." : null),
  },
  {
    key: "words_count", group: "words", module: "words_count", kind: "number", min: 1, max: 30, required: true, label: "Число слов (от 1 до 30)",
    hint: (c) => (c.mode === "edit" ? "Увеличить можно всегда, уменьшить — пока убираемые слова не начаты." : null),
  },
  {
    key: "individual_words", group: "words", module: "individual_words", kind: "checkbox", label: "У каждого участника свой набор слов",
    hint: (c) => (c.mode === "edit" ? "Менять режим можно, пока никто не сделал ни одной догадки: слова пересоздаются заново." : null),
  },

  { key: "duration_days", group: "format", module: "duration", kind: "number", min: 1, required: true, label: "Длительность (дней)" },
  {
    key: "bracket_size", group: "format", module: "bracket_size", kind: "number", min: 2, required: true, createOnly: true,
    label: "Размер сетки", hint: (c) => BRACKET_HINT[c.type],
  },
  {
    key: "end_date", group: "format", module: "end_date", kind: "date",
    label: (c) => (END_DATE_LABEL[c.type] || END_DATE_LABEL.marathon)[c.mode],
    min: (c) => (c.mode === "edit" ? c.tournament.start_date : c.values.start_date || undefined),
    hint: (c) => (c.mode === "edit" && c.type === "tiebreak"
      ? "Игроки могут играть раунд до конца этого дня; тай-брейк закрывается, когда доиграли все, либо по истечении срока."
      : null),
  },
  {
    key: "first_place", group: "format", module: "first_place", kind: "number", min: 1, editOnly: true,
    label: "Первое разыгрываемое место (например, 13, если разыгрываются места 13-15)",
  },
  {
    key: "third_place_match", group: "format", module: "third_place", kind: "checkbox", label: "Игра за 3 место", editOnly: true,
    show: (c) => (c.tournament.bracket_size || 0) >= 4,
    hint: () => "Проигравшие полуфиналов играют отдельную игру в день финала. Включить можно в любой день до конца розыгрыша, отключить — пока в игре нет ни одной догадки.",
  },

  {
    key: "teams_enabled", group: "extras", module: "teams", kind: "checkbox", editOnly: true,
    label: (c) => TEAMS_LABEL[c.type] || "Командный зачёт", hint: (c) => TEAMS_HINT[c.type],
    warn: (c) => (c.type === "marathon" && c.values.teams_enabled && !c.values.individual_words
      ? "Внимание: у всех общий набор слов — участники одной команды могут подсказывать друг другу ответы. Командный зачёт рассчитан на личные наборы слов."
      : null),
  },
  { key: "bonus", group: "extras", module: "bonus", kind: "bonus", label: "Бонусные слова" },

  { key: "notify_admin", group: "notify", kind: "notify", editOnly: true, label: "Уведомлять меня в Telegram, когда игрок закончил партию" },
];

export function defaultValues() {
  return {
    title: "", start_date: "", hashtag: "", note: "", word_length: 5, words_count: 5, individual_words: false,
    duration_days: 20, bracket_size: 16, end_date: "", first_place: 1, third_place_match: false, teams_enabled: false,
    bonus_enabled: false, bonus_every_days: 5, bonus_default_length: 6, notify_admin: false,
  };
}

export function valuesFromTournament(t) {
  return {
    title: t.title, start_date: t.start_date, hashtag: t.hashtag || "", note: t.note || "", word_length: t.word_length || 5,
    words_count: t.words_count ?? "", individual_words: !!t.individual_words, duration_days: t.duration_days ?? "",
    bracket_size: t.bracket_size ?? "", end_date: t.end_date || "", first_place: t.first_place ?? 1,
    third_place_match: !!t.third_place_match, teams_enabled: !!t.teams_enabled, bonus_enabled: !!t.bonus_enabled,
    bonus_every_days: t.bonus_every_days ?? "", bonus_default_length: t.bonus_default_length || 6, notify_admin: !!t.notify_admin,
  };
}

function createPayload(type, v, has) {
  return {
    title: v.title,
    type,
    start_date: v.start_date,
    duration_days: has("duration") ? Number(v.duration_days) : null,
    scoring_rules: DEFAULT_SCORING,
    skip_flag_symbol: "🚩",
    bracket_size: has("bracket_size") ? Number(v.bracket_size) : null,
    words_count: has("words_count") ? Number(v.words_count) : null,
    individual_words: has("individual_words") ? v.individual_words : false,
    word_length: v.word_length,
    bonus_enabled: has("bonus") && v.bonus_enabled,
    bonus_every_days: has("bonus") && v.bonus_enabled ? Number(v.bonus_every_days) : null,
    bonus_default_length: Number(v.bonus_default_length),
    end_date: has("end_date") && v.end_date ? v.end_date : null,
    rounds_per_match: 1,
    hashtag: v.hashtag.trim() || null,
    note: v.note.trim() || null,
  };
}

function settingsPayload(t, v, has, todayIso) {
  const body = { title: v.title, hashtag: v.hashtag, note: v.note, notify_admin: v.notify_admin };
  if (has("first_place")) body.first_place = Number(v.first_place) || 1;
  if (has("teams")) body.teams_enabled = v.teams_enabled;
  if (has("end_date")) {
    if (v.end_date) body.end_date = v.end_date;
    else if (t.end_date) body.clear_end_date = true;
  }
  if (has("third_place") && (t.bracket_size || 0) >= 4) body.third_place_match = v.third_place_match;
  if (has("words_count")) body.words_count = Number(v.words_count);
  if (has("individual_words")) body.individual_words = v.individual_words;
  if (t.duration_days != null) body.duration_days = Number(v.duration_days);
  if (has("bonus")) {
    body.bonus_enabled = v.bonus_enabled;
    if (v.bonus_enabled) body.bonus_every_days = Number(v.bonus_every_days);
    body.bonus_default_length = Number(v.bonus_default_length);
  }
  if (t.start_date >= todayIso && v.start_date !== t.start_date) body.start_date = v.start_date;
  return body;
}

// Строка со сводкой настроек в карточке розыгрыша (без названия режима и статуса)
export function summaryOf(t) {
  const parts = [t.start_date];
  if (t.duration_days != null) parts.push(`${t.duration_days} дн.`);
  if (t.word_length && t.word_length !== 5) parts.push(`${t.word_length} букв`);
  if (t.words_count != null) parts.push(`${t.words_count} сл.${t.individual_words ? " (личные)" : ""}`);
  if (t.teams_enabled) parts.push("команды");
  if (t.end_date) parts.push(`до ${t.end_date}`);
  if (t.bonus_enabled) parts.push(`бонусы каждые ${t.bonus_every_days} дн.`);
  return parts.join(" · ");
}

const labelStyle = { fontSize: 13, opacity: 0.85, display: "block" };
const hintStyle = { fontSize: 12, opacity: 0.6, marginTop: 3 };

function TelegramTest() {
  const [result, setResult] = useState(null); // { ok, detail } | null

  async function run() {
    setResult({ ok: null, detail: "Отправляю..." });
    try {
      setResult(await api("/api/admin/telegram/test", { method: "POST" }));
    } catch (e) {
      setResult({ ok: false, detail: e.message });
    }
  }

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 6, fontSize: 12 }}>
      <button type="button" onClick={run} style={ghostButtonStyle}>Отправить тестовое сообщение</button>
      {result && (
        <span style={{ color: result.ok === false ? "#e5484d" : result.ok ? "#538d4e" : undefined, opacity: 0.9 }}>{result.detail}</span>
      )}
    </div>
  );
}

function FieldInput({ field, ctx, value, set }) {
  const v = ctx.values;
  const label = typeof field.label === "function" ? field.label(ctx) : field.label;
  const hint = field.hint ? field.hint(ctx) : null;
  const warn = field.warn ? field.warn(ctx) : null;
  const min = field.min && typeof field.min === "function" ? field.min(ctx) : field.min;
  const note = (
    <>
      {hint && <div style={hintStyle}>{hint}</div>}
      {warn && <div style={{ ...hintStyle, color: "#e5a94c", opacity: 1 }}>{warn}</div>}
    </>
  );

  if (field.kind === "checkbox") {
    return (
      <div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={!!value} onChange={(e) => set(field.key, e.target.checked)} />
          {label}
        </label>
        {note}
      </div>
    );
  }

  if (field.kind === "notify") {
    return (
      <div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={!!value} onChange={(e) => set(field.key, e.target.checked)} />
          {label}
        </label>
        <TelegramTest />
      </div>
    );
  }

  if (field.kind === "bonus") {
    const days = bonusDays(v.duration_days, v.bonus_every_days);
    return (
      <div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={v.bonus_enabled} onChange={(e) => set("bonus_enabled", e.target.checked)} />
          {label}
        </label>
        {v.bonus_enabled && (
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginTop: 6, fontSize: 13 }}>
            <label>
              за каждые{" "}
              <input
                type="number" min={1} max={Number(v.duration_days) || undefined} value={v.bonus_every_days}
                onChange={(e) => set("bonus_every_days", e.target.value)} style={{ ...inputStyle, width: 70, display: "inline-block" }}
              />{" "}
              дн. без пропуска
            </label>
            <label>
              длина новых слов{" "}
              <select
                value={v.bonus_default_length} onChange={(e) => set("bonus_default_length", Number(e.target.value))}
                style={{ ...inputStyle, width: "auto", display: "inline-block" }}
              >
                {LENGTHS.map((n) => <option key={n} value={n}>{n} букв</option>)}
              </select>
            </label>
          </div>
        )}
        <div style={hintStyle}>
          Игрок, не пропустивший ни одного дня блока из N дней, получает право в последний день блока (после слова дня)
          отгадать бонусное слово за очки по шкале розыгрыша — только в этот день.
          {v.bonus_enabled && (days.length > 0
            ? ` Бонусы откроются в дни: ${days.join(", ")}.${ctx.mode === "create" ? " Длину каждого слова можно будет изменить отдельно." : ""}`
            : " При такой длительности бонусных слов не будет — уменьшите N.")}
          {ctx.mode === "edit" && ctx.tournament.bonus_enabled && " Менять N и выключать бонусы можно, пока их никто не сыграл."}
        </div>
      </div>
    );
  }

  let control;
  if (field.kind === "textarea") {
    control = (
      <textarea
        value={value} onChange={(e) => set(field.key, e.target.value)} placeholder={field.placeholder}
        style={{ ...inputStyle, minHeight: 56, resize: "vertical", width: "100%", boxSizing: "border-box" }}
      />
    );
  } else if (field.kind === "length") {
    control = (
      <select value={value} onChange={(e) => set(field.key, Number(e.target.value))} style={{ ...inputStyle, display: "block" }}>
        {LENGTHS.map((n) => <option key={n} value={n}>{n} букв{n === 5 ? " (обычная)" : ""}</option>)}
      </select>
    );
  } else {
    control = (
      <input
        type={field.kind} value={value} min={min} max={field.max} required={field.required} placeholder={field.placeholder}
        onChange={(e) => set(field.key, e.target.value)}
        style={{ ...inputStyle, ...(field.kind === "text" ? { width: "100%", boxSizing: "border-box" } : { display: "block" }) }}
      />
    );
  }
  return (
    <label style={labelStyle}>
      {label}
      <div style={{ marginTop: 3 }}>{control}</div>
      {note}
    </label>
  );
}

// Поля формы по группам для режима `type`; mode — "create" (мастер) или "edit" (настройки розыгрыша).
function FieldsForm({ type, mode, values, set, tournament }) {
  const { has } = useModes();
  const ctx = { mode, type, tournament, values, todayIso: new Date().toISOString().slice(0, 10), has: (m) => has(type, m) };
  const visible = FIELDS.filter((f) => (
    (!f.module || has(type, f.module))
    && (mode === "create" ? !f.editOnly : !f.createOnly)
    && (!f.show || f.show(ctx))
  ));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {GROUPS.map((g) => {
        const fields = visible.filter((f) => f.group === g.key);
        if (fields.length === 0) return null;
        return (
          <div key={g.key}>
            <div style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: 1, opacity: 0.5, marginBottom: 8 }}>{g.label}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {fields.map((f) => <FieldInput key={f.key} field={f} ctx={ctx} value={values[f.key]} set={set} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Мастер создания: сначала режим (с описанием), затем поля этого режима.
export function CreateWizard({ onCreated, onCancel }) {
  const { list, has, label } = useModes();
  const [type, setType] = useState(null);
  const [values, setValues] = useState(defaultValues);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key, value) => setValues((prev) => ({ ...prev, [key]: value }));

  async function handleCreate(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api("/api/admin/tournaments", { method: "POST", body: JSON.stringify(createPayload(type, values, (m) => has(type, m))) });
      setValues(defaultValues());
      await onCreated();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!type) {
    return (
      <div style={{ marginTop: 8 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Какой режим?</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {list.map((m) => (
            <button
              key={m.type} type="button" onClick={() => setType(m.type)}
              style={{ ...ghostButtonStyle, textAlign: "left", padding: "8px 10px" }}
            >
              <div style={{ fontWeight: 600, fontSize: 14 }}>{m.label}</div>
              <div style={{ fontSize: 12, opacity: 0.65, marginTop: 2, whiteSpace: "normal" }}>{m.summary}</div>
            </button>
          ))}
        </div>
        <button type="button" onClick={onCancel} style={{ ...ghostButtonStyle, marginTop: 8 }}>Отмена</button>
      </div>
    );
  }

  return (
    <form onSubmit={handleCreate} style={{ marginTop: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 8 }}>
        <div style={{ fontWeight: 600 }}>Новый розыгрыш · {label(type)}</div>
        <button type="button" onClick={() => setType(null)} style={ghostButtonStyle}>← другой режим</button>
      </div>
      <FieldsForm type={type} mode="create" values={values} set={set} />
      {error && <div style={{ color: "#e5484d", marginTop: 10 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button type="submit" disabled={busy} style={buttonStyle}>Создать</button>
        <button type="button" onClick={onCancel} style={ghostButtonStyle}>Отмена</button>
      </div>
    </form>
  );
}

// Подвкладка «Настройки» розыгрыша: те же поля, что в мастере, плюс изменяемые после создания.
export function TournamentSettings({ tournament, onSaved }) {
  const { has } = useModes();
  const [values, setValues] = useState(() => valuesFromTournament(tournament));
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const set = (key, value) => {
    setSaved(false);
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  async function handleSave(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const todayIso = new Date().toISOString().slice(0, 10);
      await api(`/api/admin/tournaments/${tournament.id}`, {
        method: "PATCH", body: JSON.stringify(settingsPayload(tournament, values, (m) => has(tournament.type, m), todayIso)),
      });
      await onSaved();
      setSaved(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSave} style={{ background: "#1c1c1e", borderRadius: 10, padding: 16, marginTop: 20, maxWidth: 640 }}>
      <h3 style={{ marginTop: 0 }}>Настройки «{tournament.title}»</h3>
      <FieldsForm type={tournament.type} mode="edit" values={values} set={set} tournament={tournament} />
      {error && <div style={{ color: "#e5484d", marginTop: 10 }}>{error}</div>}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14 }}>
        <button type="submit" disabled={busy} style={buttonStyle}>Сохранить</button>
        {saved && <span style={{ fontSize: 13, color: "#538d4e" }}>Сохранено</span>}
      </div>
    </form>
  );
}
