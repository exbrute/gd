const { useEffect, useState } = React;

const MODES = {
  short: "Кратко",
  detailed: "Подробно",
};

const TABS = {
  solve: { label: "Задачи", icon: "📚" },
  profile: { label: "Профиль", icon: "👤" },
  settings: { label: "Настройки", icon: "⚙️" },
};

function getTelegramUser() {
  try {
    return window.Telegram?.WebApp?.initDataUnsafe?.user || null;
  } catch { return null; }
}

function getInitData() {
  try {
    return window.Telegram?.WebApp?.initData || "";
  } catch { return ""; }
}

function authHeaders(extra = {}) {
  return {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": getInitData(),
    ...extra,
  };
}

function useTelegramTheme() {
  useEffect(() => {
    if (window.Telegram?.WebApp) {
      const app = window.Telegram.WebApp;
      app.ready();
      app.expand();
      app.setHeaderColor("#0b1120");
      app.setBackgroundColor("#020617");
    }
  }, []);
}

function useTelegramUser() {
  const [tgUser, setTgUser] = useState(null);

  useEffect(() => {
    function tryGet() {
      const u = window.Telegram?.WebApp?.initDataUnsafe?.user;
      if (u?.id) return u;
      try {
        const raw = window.Telegram?.WebApp?.initData;
        if (raw) {
          const p = new URLSearchParams(raw);
          const j = p.get("user");
          if (j) return JSON.parse(j);
        }
      } catch {}
      return null;
    }

    const user = tryGet();
    if (user?.id) { setTgUser(user); return; }

    let tries = 0;
    const interval = setInterval(() => {
      tries++;
      const u = tryGet();
      if (u?.id) { setTgUser(u); clearInterval(interval); }
      if (tries > 20) clearInterval(interval);
    }, 200);

    return () => clearInterval(interval);
  }, []);

  return tgUser;
}

function Status({ text, tone }) {
  if (!text) return null;
  return (
    <div className={`status status--${tone}`}>
      <span className="status-dot" />
      <span>{text}</span>
    </div>
  );
}

const GENERATION_STEPS = [
  { emoji: "🔍", text: "Распознаём текст..." },
  { emoji: "📖", text: "Анализируем условие..." },
  { emoji: "🧠", text: "Строим решение..." },
  { emoji: "✏️", text: "Проверяем вычисления..." },
];

function GeneratingScreen({ status }) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    const t = setInterval(() => {
      setStepIndex((i) => (i + 1) % GENERATION_STEPS.length);
    }, 2200);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="generating-page">
      <div className="generating-card glass">
        <div className="generating-steps">
          {GENERATION_STEPS.map((step, i) => (
            <div
              key={i}
              className={`generating-step ${i === stepIndex ? "generating-step--active" : ""}`}
            >
              <span className="generating-step-emoji">{step.emoji}</span>
              <span className="generating-step-text">{step.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SolveSection({
  mode,
  text,
  fileName,
  loading,
  status,
  statusTone,
  onModeClick,
  onTextChange,
  onFileChange,
  onSolve,
}) {
  return (
    <section className="solver-card glass">
      <div className="mode-switch">
        {Object.entries(MODES).map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={`mode-btn ${mode === value ? "mode-btn--active" : ""}`}
            onClick={() => onModeClick(value)}
          >
            <span className="mode-icon">
              {value === "short" ? "⚡" : "🧠"}
            </span>
            {label}
          </button>
        ))}
      </div>

      <label className="field">
        <span className="field-label">Текст задачи</span>
        <textarea
          className="field-input"
          placeholder="Вставьте текст задания или скопируйте условие из фото..."
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          rows={5}
        />
      </label>

      <div className="upload-row">
        <button
          id="upload-btn"
          className="primary-ghost-btn"
          type="button"
          onClick={() => document.getElementById("file-input").click()}
        >
          Загрузить фото
        </button>
        <input
          id="file-input"
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => onFileChange(e.target.files?.[0])}
        />
        <span className="file-name">
          {fileName || "Файл не выбран"}
        </span>
      </div>

      <button
        id="solve-btn"
        className="primary-btn"
        type="button"
        onClick={onSolve}
        disabled={loading}
      >
        <span>{loading ? "Генерация..." : "Сгенерировать решение"}</span>
        <span className="btn-glow" />
      </button>

      <Status text={status} tone={statusTone} />
    </section>
  );
}

const FREE_LIMIT = 10;

function ProfileSection({
  solvedCount,
  availableRequests,
  isPro,
  displayName,
  daysUntilUpdate,
}) {
  const used = Math.min(solvedCount, FREE_LIMIT);
  const remaining = isPro ? null : (typeof availableRequests === "number" ? availableRequests : FREE_LIMIT - used);
  const days = daysUntilUpdate ?? 0;

  return (
    <section className="profile-card glass">
      <div className="profile-main">
        <div className="profile-avatar">
          <span>{(displayName || "У")[0].toUpperCase()}</span>
        </div>
        <div>
          <div className="profile-name">{displayName}</div>
          <div className="profile-tag">{isPro ? "Pro-подписка" : "Бесплатный план"}</div>
        </div>
      </div>

      {!isPro && (
        <div className="profile-limit-block">
          <h3 className="profile-limit-title">
            <span className="profile-limit-icon" aria-hidden>📊</span>
            Прогресс-бар использования лимита
          </h3>
          <div className="profile-limit-row">
            <span className="profile-limit-icon" aria-hidden>📅</span>
            <span>До обновления: {days} {days === 1 ? "день" : days < 5 ? "дня" : "дней"}</span>
          </div>
          <div className="profile-limit-row">
            <span className="profile-limit-icon" aria-hidden>📈</span>
            <span>Сегодня решено: {solvedCount}</span>
          </div>
          <div className="profile-limit-example">
            <div className="profile-limit-example-label">Пример:</div>
            <div>Использовано {used} из {FREE_LIMIT}</div>
            <div>Обновление через {days} {days === 1 ? "день" : days < 5 ? "дня" : "дней"}</div>
          </div>
          <div className="profile-limit-bar-wrap">
            <div
              className="profile-limit-bar-fill"
              style={{ width: `${Math.min(100, (used / FREE_LIMIT) * 100)}%` }}
            />
          </div>
        </div>
      )}

      <div className="profile-stats">
        <div className="profile-stat">
          <div className="profile-stat-value">{solvedCount}</div>
          <div className="profile-stat-label">Решено задач</div>
        </div>
        <div className="profile-stat">
          <div className="profile-stat-value">{isPro ? "∞" : remaining}</div>
          <div className="profile-stat-label">Осталось</div>
        </div>
        <div className="profile-stat">
          <div className="profile-stat-value">{isPro ? "PRO" : "FREE"}</div>
          <div className="profile-stat-label">Подписка</div>
        </div>
      </div>

      <div className="profile-note">
        {isPro
          ? "У тебя безлимит — решай сколько хочешь!"
          : "10 запросов каждые 7 дней. Хочешь безлимит? Оформи Pro."}
      </div>
    </section>
  );
}

function SettingsSection({ defaultDetailMode, onChangeDefaultDetail }) {
  return (
    <section className="settings-card glass">
      <h2 className="section-title">Настройки</h2>

      <div className="setting-row">
        <div>
          <div className="setting-title">Детализация по умолчанию</div>
          <div className="setting-subtitle">
            Как бот будет отвечать, если не менять режим вручную.
          </div>
        </div>
        <div className="setting-toggle-group">
          <button
            type="button"
            className={`setting-toggle ${defaultDetailMode === "short" ? "setting-toggle--active" : ""}`}
            onClick={() => onChangeDefaultDetail("short")}
          >
            Кратко
          </button>
          <button
            type="button"
            className={`setting-toggle ${defaultDetailMode === "detailed" ? "setting-toggle--active" : ""}`}
            onClick={() => onChangeDefaultDetail("detailed")}
          >
            Подробно
          </button>
        </div>
      </div>

      <div className="setting-row">
        <div>
          <div className="setting-title">Тёмная тема</div>
          <div className="setting-subtitle">
            Интерфейс оптимизирован под вечерние сессии. Светлая тема появится позже.
          </div>
        </div>
      </div>
    </section>
  );
}

function AppShell() {
  useTelegramTheme();

  const [activeTab, setActiveTab] = useState("solve");
  const [mode, setMode] = useState("short");
  const [defaultDetailMode, setDefaultDetailMode] = useState("short");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [imageBase64, setImageBase64] = useState(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState("neutral");
  const [view, setView] = useState("form"); // "form" | "generating"
  const [solvedCount, setSolvedCount] = useState(0);
  const [availableRequests, setAvailableRequests] = useState("...");
  const [daysUntilUpdate, setDaysUntilUpdate] = useState(7);
  const [isPro, setIsPro] = useState(false);
  const [telegramId, setTelegramId] = useState(null);
  const [displayName, setDisplayName] = useState("Ученик");

  useEffect(() => {
    setMode(defaultDetailMode);
  }, [defaultDetailMode]);

  useEffect(() => {
    const init = () => {
      const initData = getInitData();
      fetch("/api/me", {
        headers: { "X-Telegram-Init-Data": initData }
      })
        .then(r => r.json())
        .then(data => {
          if (data.telegram_id) setTelegramId(data.telegram_id);
          if (data.first_name) setDisplayName(data.first_name);
          else if (data.username) setDisplayName(data.username);
          setAvailableRequests(data.remaining);
          setIsPro(data.is_pro || false);
          setSolvedCount(data.requests_used || 0);
          if (typeof data.days_until_update === "number") setDaysUntilUpdate(data.days_until_update);
        })
        .catch(() => setAvailableRequests(10));
    };

    if (window.Telegram?.WebApp?.initData) {
      init();
    } else {
      setTimeout(init, 500);
    }
  }, []);

  const handleFileChange = (file) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setStatusTone("error");
      setStatus("Можно загрузить только изображение.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      const base64 = result.split(",")[1] || result;
      setImageBase64(base64);
      setFileName(file.name);
      setStatusTone("neutral");
      setStatus("Фото прикреплено. Можно отправлять на решение.");
    };
    reader.readAsDataURL(file);
  };

  const handleSolve = async () => {
    if (!text.trim() && !imageBase64) {
      setStatusTone("error");
      setStatus("Введите текст задачи или загрузите фото.");
      return;
    }

    if (!isPro && typeof availableRequests === "number" && availableRequests <= 0) {
      setStatusTone("error");
      setStatus("Лимит запросов исчерпан. Подождите 7 дней или оформите Pro.");
      return;
    }

    setView("generating");
    setLoading(true);
    setStatus("Генерирую решение...");

    try {
      const resp = await fetch("/api/solve", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          text: text.trim() || null,
          detail: mode === "short" ? "short" : "detailed",
          image_base64: imageBase64,
          telegram_id: telegramId,
        }),
      });

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || "Ошибка при обращении к серверу.");
      }

      const data = await resp.json();
      const answerText = data.answer || "";
      setSolvedCount((prev) => prev + 1);
      if (!isPro) setAvailableRequests((prev) => typeof prev === "number" ? Math.max(0, prev - 1) : prev);

      const solResp = await fetch("/api/solution", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ answer: answerText }),
      });
      if (!solResp.ok) throw new Error("Не удалось создать страницу решения.");
      const { url } = await solResp.json();
      window.location.href = url;
    } catch (err) {
      setView("form");
      setStatusTone("error");
      setStatus(err.message || "Что-то пошло не так. Попробуйте ещё раз.");
    } finally {
      setLoading(false);
    }
  };

  const onModeClick = (value) => {
    setMode(value);
  };

  const handleChangeDefaultDetail = (value) => {
    setDefaultDetailMode(value);
  };

  if (view === "generating") {
    return (
      <div className="app-shell">
        <GeneratingScreen status={status} />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header glass">
        <div className="app-logo">TESTAI</div>
        <div className="app-header-right">
          <span className="app-badge">RAZUMION MINI APP</span>
          <div className="app-dot-pulse" aria-hidden="true" />
        </div>
      </header>

      <main className="app-main">
        <section className="hero-card glass">
          <h1 className="hero-title">Решение задач в один клик</h1>
          <p className="hero-subtitle">
            Вставьте текст или фото. Ответ откроется на отдельной странице —
            с оформленными формулами и пошаговым решением.
          </p>
          <div className="hero-tags">
            <span className="hero-tag">Домашка</span>
            <span className="hero-tag">Тесты</span>
            <span className="hero-tag">Контрольные</span>
          </div>
          <div className="user-chip">
            {isPro ? "PRO — безлимит" : `Осталось запросов: ${availableRequests}`}
          </div>
        </section>

        <nav className="tab-bar glass">
          {Object.entries(TABS).map(([id, { label, icon }]) => (
            <button
              key={id}
              type="button"
              className={`tab-item ${activeTab === id ? "tab-item--active" : ""}`}
              onClick={() => setActiveTab(id)}
            >
              <span className="tab-icon">{icon}</span>
              <span className="tab-label">{label}</span>
            </button>
          ))}
        </nav>

        <div className="tab-panels">
          {activeTab === "solve" && (
            <SolveSection
              mode={mode}
              text={text}
              fileName={fileName}
              loading={loading}
              status={status}
              statusTone={statusTone}
              onModeClick={onModeClick}
              onTextChange={setText}
              onFileChange={handleFileChange}
              onSolve={handleSolve}
            />
          )}

          {activeTab === "profile" && (
            <ProfileSection
              solvedCount={solvedCount}
              availableRequests={availableRequests}
              isPro={isPro}
              displayName={displayName}
              daysUntilUpdate={daysUntilUpdate}
            />
          )}

          {activeTab === "settings" && (
            <SettingsSection
              defaultDetailMode={defaultDetailMode}
              onChangeDefaultDetail={handleChangeDefaultDetail}
            />
          )}
        </div>
      </main>
    </div>
  );
}

function Root() {
  return (
    <React.StrictMode>
      <div className="app-bg-blur" />
      <AppShell />
    </React.StrictMode>
  );
}

const container = document.getElementById("app-root");
const root = ReactDOM.createRoot(container);
root.render(<Root />);


