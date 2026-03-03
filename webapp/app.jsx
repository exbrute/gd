const { useCallback, useEffect, useState } = React;

const MODES = {
  short: "Кратко",
  detailed: "Подробно",
};

const TABS = {
  solve: { label: "Задачи", icon: "📚" },
  profile: { label: "Профиль", icon: "👤" },
  pay: { label: "Pro", icon: "⚡" },
  settings: { label: "Настройки", icon: "⚙️" },
};

const INIT_DATA_KEY = "tg_init_data";

function readInitDataFromTelegram() {
  try {
    const twa = window.Telegram?.WebApp;
    if (!twa) return "";
    twa.ready && twa.ready();
    return twa.initData || "";
  } catch { return ""; }
}

function readInitDataFromUrl() {
  try {
    const hash = (window.location.hash || "").replace(/^#/, "").trim();
    const search = (window.location.search || "").replace(/^\?/, "").trim();
    const params = new URLSearchParams(hash || search);
    const fromParam = params.get("tgWebAppData") || params.get("initData") || params.get("tgWebAppDataRaw");
    if (fromParam) return fromParam;
    if (hash && hash.includes("hash=") && hash.includes("auth_date=")) return hash;
    return "";
  } catch { return ""; }
}

function getInitData() {
  let data = readInitDataFromTelegram();
  if (!data) data = readInitDataFromUrl();
  if (!data) data = sessionStorage.getItem(INIT_DATA_KEY) || "";
  if (data) sessionStorage.setItem(INIT_DATA_KEY, data);
  return data || "";
}

function getTelegramUser() {
  try {
    const u = window.Telegram?.WebApp?.initDataUnsafe?.user;
    if (u?.id) return u;
    const raw = getInitData();
    if (!raw) return null;
    const p = new URLSearchParams(raw);
    const j = p.get("user");
    return j ? JSON.parse(j) : null;
  } catch { return null; }
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
    const twa = window.Telegram?.WebApp;
    if (twa) {
      twa.ready();
      twa.expand();
      twa.setHeaderColor("#0b1120");
      twa.setBackgroundColor("#020617");
      const save = () => {
        const data = twa.initData || readInitDataFromUrl();
        if (data) sessionStorage.setItem(INIT_DATA_KEY, data);
      };
      save();
      const t = setInterval(save, 300);
      return () => clearInterval(t);
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

function pluralRequests(n) {
  if (n === 1) return "запрос";
  if (n >= 2 && n <= 4) return "запроса";
  return "запросов";
}

function GeneratingScreen({ status, availableRequests, isPro }) {
  const [stepIndex, setStepIndex] = useState(0);
  const showLowLimit = !isPro && typeof availableRequests === "number" && availableRequests <= 2;

  useEffect(() => {
    const t = setInterval(() => {
      setStepIndex((i) => (i + 1) % GENERATION_STEPS.length);
    }, 2200);
    return () => clearInterval(t);
  }, []);

  const step = GENERATION_STEPS[stepIndex];

  return (
    <div className="generating-page">
      {showLowLimit && (
        <div className="generating-warning glass">
          <div className="generating-warning-top">
            <span>Осталось {availableRequests} {pluralRequests(availableRequests)}</span>
            <span className="generating-warning-icon" aria-hidden>⚠️</span>
          </div>
          <p className="generating-warning-text">
            Чтобы не остаться без решения на контрольной —
          </p>
          <a href="/#pay" className="generating-warning-cta">подключи PRO</a>
        </div>
      )}
      <div className="generating-card glass">
        <div className="generating-steps generating-steps--single">
          <div key={stepIndex} className="generating-step">
            <span className="generating-step-emoji">{step.emoji}</span>
            <span className="generating-step-text">{step.text}</span>
          </div>
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
  telegramId,
}) {
  const used = Math.min(solvedCount, FREE_LIMIT);
  const remaining = isPro ? null : (typeof availableRequests === "number" ? availableRequests : FREE_LIMIT - used);
  const days = daysUntilUpdate ?? 0;

  return (
    <section className="profile-card glass">
      {!telegramId && (
        <div className="status status--error" style={{ marginBottom: 16 }}>
          <span className="status-dot" />
          <span>Нажмите кнопку «📚 Открыть TestAI» под сообщением бота (отправьте /start, затем кнопку).</span>
        </div>
      )}
      <div className="profile-main">
        <div className="profile-avatar">
          <span>{(displayName || "У")[0].toUpperCase()}</span>
        </div>
        <div>
          <div className="profile-name">{displayName}</div>
          <div className={`profile-tag ${isPro ? "profile-tag--pro" : ""}`}>{isPro ? "Pro-подписка" : "Бесплатный план"}</div>
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
        <div className={`profile-stat ${isPro ? "profile-stat--pro" : ""}`}>
          <div className="profile-stat-value">{isPro ? "∞" : remaining}</div>
          <div className="profile-stat-label">Осталось</div>
        </div>
        <div className={`profile-stat ${isPro ? "profile-stat--pro" : ""}`}>
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

const PAYMENT_METHODS = [
  { id: "sbp", label: "СБП", icon: "🏦", desc: "Оплата через Систему быстрых платежей" },
  { id: "cryptobot", label: "CryptoBot", icon: "₿", desc: "Оплата криптовалютой в Telegram" },
];

function PaySection({ isPro, onRefresh }) {
  const [selectedMethod, setSelectedMethod] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const handlePay = async (methodId) => {
    const initData = getInitData();
    if (!initData) {
      setError("Не удалось получить данные авторизации. Закройте и откройте приложение заново из чата с ботом.");
      return;
    }
    setLoading(true);
    setError("");
    setStatus("");
    try {
      const resp = await fetch("/api/pay/create", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          method: methodId,
          init_data: initData || undefined,
        }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || "Ошибка создания платежа");
      if (data.url) {
        window.location.href = data.url;
      } else if (data.qr_url) {
        window.open(data.qr_url, "_blank");
      } else {
        setStatus("Платёж создан. API интеграция — подключите провайдера.");
      }
    } catch (err) {
      setError(err.message || "Не удалось создать платёж");
    } finally {
      setLoading(false);
    }
  };

  if (isPro) {
    return (
      <section className="pay-card glass">
        <div className="pay-pro-badge">У тебя уже Pro</div>
        <p className="pay-pro-text">Безлимит задач уже подключён. Продолжай решать!</p>
      </section>
    );
  }

  return (
    <section className="pay-card glass">
      <h2 className="section-title">Оформление Pro</h2>
      <p className="pay-subtitle">Безлимит задач, приоритетная скорость, решение «как в тетради»</p>

      <div className="pay-methods">
        {PAYMENT_METHODS.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`pay-method-btn ${selectedMethod === m.id ? "pay-method-btn--active" : ""}`}
            onClick={() => setSelectedMethod(m.id)}
          >
            <span className="pay-method-icon">{m.icon}</span>
            <div className="pay-method-info">
              <span className="pay-method-label">{m.label}</span>
              <span className="pay-method-desc">{m.desc}</span>
            </div>
          </button>
        ))}
      </div>

      {error && <div className="status status--error">{error}</div>}
      {status && <div className="status status--success">{status}</div>}

      <button
        className="primary-btn"
        type="button"
        disabled={!selectedMethod || loading}
        onClick={() => selectedMethod && handlePay(selectedMethod)}
      >
        {loading ? "Создаём платёж..." : selectedMethod
          ? `Оплатить через ${selectedMethod === "sbp" ? "СБП" : "CryptoBot"}`
          : "Выберите способ оплаты"}
      </button>

      <p className="pay-note">CryptoBot подключён. СБП — в разработке.</p>
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
  const [initialTab, setInitialTab] = useState(null);
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
    const hash = (window.location.hash || "").replace("#", "");
    const path = (window.location.pathname || "").replace(/\/$/, "") || "/";
    if (hash === "pay" || path === "/pay") setInitialTab("pay");
  }, []);

  const effectiveTab = initialTab !== null ? initialTab : activeTab;
  const setEffectiveTab = (t) => {
    setInitialTab(null);
    setActiveTab(t);
  };

  useEffect(() => {
    const init = () => {
      const initData = getInitData();
      const url = initData ? `/api/me?init_data=${encodeURIComponent(initData)}` : "/api/me";
      return fetch(url, {
        headers: { "X-Telegram-Init-Data": initData }
      })
        .then(r => r.json())
        .then(data => {
          if (data.telegram_id) {
            setTelegramId(data.telegram_id);
            setSolvedCount(data.requests_used || 0);
            if (typeof data.days_until_update === "number") setDaysUntilUpdate(data.days_until_update);
          } else {
            setSolvedCount(0);
          }
          setAvailableRequests(data.remaining ?? 10);
          setIsPro(data.is_pro || false);
          if (data.first_name) setDisplayName(data.first_name);
          else if (data.username) setDisplayName(data.username);
          return data.telegram_id;
        })
        .catch(() => { setAvailableRequests(10); return null; });
    };

    init().then((uid) => {
      if (!uid && window.Telegram?.WebApp) {
        [800, 2000, 4000].forEach((ms) => setTimeout(init, ms));
      }
    });
  }, []);

  const refreshMe = useCallback(() => {
    const initData = getInitData();
    const url = initData ? `/api/me?init_data=${encodeURIComponent(initData)}` : "/api/me";
    fetch(url, { headers: { "X-Telegram-Init-Data": initData } })
      .then(r => r.json())
      .then(data => {
        if (data.telegram_id) {
          setTelegramId(data.telegram_id);
          setSolvedCount(data.requests_used || 0);
          if (typeof data.days_until_update === "number") setDaysUntilUpdate(data.days_until_update);
        } else {
          setSolvedCount(0);
        }
        setAvailableRequests(data.remaining ?? 10);
        setIsPro(data.is_pro || false);
        if (data.first_name) setDisplayName(data.first_name);
        else if (data.username) setDisplayName(data.username);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (effectiveTab === "profile") refreshMe();
  }, [effectiveTab, refreshMe]);

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
          init_data: getInitData() || undefined,
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
        <GeneratingScreen
          status={status}
          availableRequests={availableRequests}
          isPro={isPro}
        />
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
        </section>

        <nav className="tab-bar glass">
          {Object.entries(TABS).map(([id, { label, icon }]) => (
            <button
              key={id}
              type="button"
              className={`tab-item ${effectiveTab === id ? "tab-item--active" : ""}`}
              onClick={() => setEffectiveTab(id)}
            >
              <span className="tab-icon">{icon}</span>
              <span className="tab-label">{label}</span>
            </button>
          ))}
        </nav>

        <div className="tab-panels">
          {effectiveTab === "solve" && (
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

          {effectiveTab === "profile" && (
            <ProfileSection
              solvedCount={solvedCount}
              availableRequests={availableRequests}
              isPro={isPro}
              displayName={displayName}
              daysUntilUpdate={daysUntilUpdate}
              telegramId={telegramId}
            />
          )}

          {effectiveTab === "pay" && (
            <PaySection isPro={isPro} onRefresh={refreshMe} />
          )}

          {effectiveTab === "settings" && (
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


