const { useCallback, useEffect, useState } = React;

const MODES = {
  short: "Кратко",
  detailed: "Подробно",
};

const TAB_ICONS = {
  solve: (
    <svg viewBox="0 0 24 24" className="tab-svg" fill="currentColor">
      <path d="M4.82931 4.60976C4.98599 4.24011 5.34854 4 5.75003 4H18.25C18.8023 4 19.25 4.44772 19.25 5C19.25 5.55228 18.8023 6 18.25 6H8.10936L13.0595 11.1152C13.4185 11.4862 13.4362 12.0694 13.1002 12.4614L7.92425 18.5H18.25C18.8023 18.5 19.25 18.9477 19.25 19.5C19.25 20.0523 18.8023 20.5 18.25 20.5H5.75003C5.3595 20.5 5.0047 20.2727 4.84151 19.9179C4.67833 19.5631 4.73662 19.1457 4.99077 18.8492L10.9889 11.8514L5.03142 5.69542C4.75223 5.40692 4.67264 4.97941 4.82931 4.60976Z" />
    </svg>
  ),
  profile: (
    <svg viewBox="0 0 20 20" className="tab-svg" fill="currentColor">
      <g transform="translate(-84, -1998)">
        <path d="M100.562548,2016.99998 L87.4381713,2016.99998 C86.7317804,2016.99998 86.2101535,2016.30298 86.4765813,2015.66198 C87.7127655,2012.69798 90.6169306,2010.99998 93.9998492,2010.99998 C97.3837885,2010.99998 100.287954,2012.69798 101.524138,2015.66198 C101.790566,2016.30298 101.268939,2016.99998 100.562548,2016.99998 M89.9166645,2004.99998 C89.9166645,2002.79398 91.7489936,2000.99998 93.9998492,2000.99998 C96.2517256,2000.99998 98.0830339,2002.79398 98.0830339,2004.99998 C98.0830339,2007.20598 96.2517256,2008.99998 93.9998492,2008.99998 C91.7489936,2008.99998 89.9166645,2007.20598 89.9166645,2004.99998 M103.955674,2016.63598 C103.213556,2013.27698 100.892265,2010.79798 97.837022,2009.67298 C99.4560048,2008.39598 100.400241,2006.33098 100.053171,2004.06998 C99.6509769,2001.44698 97.4235996,1999.34798 94.7348224,1999.04198 C91.0232075,1998.61898 87.8750721,2001.44898 87.8750721,2004.99998 C87.8750721,2006.88998 88.7692896,2008.57398 90.1636971,2009.67298 C87.1074334,2010.79798 84.7871636,2013.27698 84.044024,2016.63598 C83.7745338,2017.85698 84.7789973,2018.99998 86.0539717,2018.99998 L101.945727,2018.99998 C103.221722,2018.99998 104.226185,2017.85698 103.955674,2016.63598" />
      </g>
    </svg>
  ),
  pay: (
    <svg viewBox="0 0 24 24" className="tab-svg" fill="currentColor">
      <path d="M22.0007 12.0007C22.0007 6.47788 17.5236 2.00073 12.0007 2.00073C6.47788 2.00073 2.00073 6.47788 2.00073 12.0007C2.00073 17.5236 6.47788 22.0007 12.0007 22.0007C17.5236 22.0007 22.0007 17.5236 22.0007 12.0007ZM7.47004 12.2808C7.20377 12.0146 7.17956 11.5979 7.39742 11.3043L7.47004 11.2202L11.4709 7.21936C11.7372 6.95306 12.1539 6.92889 12.4475 7.14682L12.5316 7.21947L16.5316 11.221C16.8245 11.5139 16.8244 11.9888 16.5314 12.2817C16.2651 12.5479 15.8484 12.572 15.5549 12.3541L15.4708 12.2814L12.7501 9.55952L12.7504 16.2512C12.7504 16.6309 12.4682 16.9447 12.1021 16.9944L12.0004 17.0012C11.6207 17.0012 11.3069 16.7191 11.2572 16.353L11.2504 16.2512L11.2501 9.56152L8.5307 12.2808C8.26443 12.5471 7.84777 12.5713 7.55415 12.3535L7.47004 12.2808Z" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" className="tab-svg" fill="currentColor">
      <path d="M8.25,4 C8.66421356,4 9,4.33578644 9,4.75 L9,7.52316788 L10.8742913,10.3383227 C10.9562636,10.4614438 11,10.6060543 11,10.7539673 L11,15.25 C11,15.6642136 10.6642136,16 10.25,16 L8.99630577,16 L8.99724473,19.2535536 C8.99724473,19.6677671 8.6614583,20.0035536 8.24724473,20.0035536 C7.86754897,20.0035536 7.55375377,19.7213997 7.50409135,19.3553241 L7.49724473,19.2535536 L7.49630577,16 L5.50130577,15.999 L5.5019993,19.2565979 C5.5019993,19.6708115 5.16621287,20.0065979 4.7519993,20.0065979 C4.37230354,20.0065979 4.05850834,19.7244441 4.00884592,19.3583685 L4.0019993,19.2565979 L4.00130577,15.999 L2.75230577,16 C2.33809221,16 2.00230577,15.6642136 2.00230577,15.25 L2.00230577,10.7539673 C2.00230577,10.6060543 2.04604219,10.4614438 2.12801447,10.3383227 L4.00230577,7.52316788 L4.00230577,4.75 C4.00230577,4.33578644 4.33809221,4 4.75230577,4 L8.25,4 Z M15.2545784,4.00139149 L19.75,4.00139149 C20.1296958,4.00139149 20.443491,4.28354537 20.4931534,4.64962093 L20.5,4.75139149 L20.4993058,8 L21.25,8 C21.6642136,8 22,8.33578644 22,8.75 L22,13.2460327 C22,13.3939457 21.9562636,13.5385562 21.8742913,13.6616773 L20,16.4768321 L20,19.25 C20,19.6642136 19.6642136,20 19.25,20 L15.7523058,20 C15.3380922,20 15.0023058,19.6642136 15.0023058,19.25 L15.0023058,16.4768321 L13.1280145,13.6616773 C13.0460422,13.5385562 13.0023058,13.3939457 13.0023058,13.2460327 L13.0023058,8.75 C13.0023058,8.33578644 13.3380922,8 13.7523058,8 L14.5043058,8 L14.5045784,4.75139149 C14.5045784,4.37169572 14.7867323,4.05790053 15.1528079,4.00823811 L15.2545784,4.00139149 L19.75,4.00139149 L15.2545784,4.00139149 Z M19,5.50139149 L16.0045784,5.50139149 L16.0043058,8 L18.9993058,8 L19,5.50139149 Z" />
    </svg>
  ),
};

const TABS = {
  solve: { label: "Задачи" },
  profile: { label: "Профиль" },
  pay: { label: "Pro" },
  settings: { label: "Настройки" },
};

const INIT_DATA_KEY = "tg_init_data";
const AUTH_TOKEN_KEY = "tg_auth_token";

function getAuthToken() {
  return sessionStorage.getItem(AUTH_TOKEN_KEY) || "";
}

function setAuthToken(token) {
  if (token) sessionStorage.setItem(AUTH_TOKEN_KEY, token);
}

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
  const h = {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": getInitData(),
    ...extra,
  };
  const tok = getAuthToken();
  if (tok) h["X-Auth-Token"] = tok;
  return h;
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

function formatSolutionDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function ProfileSection({
  solvedCount,
  availableRequests,
  freeLimit = 10,
  isPro,
  displayName,
  daysUntilUpdate,
  telegramId,
  debugInfo,
}) {
  const [solutions, setSolutions] = useState([]);
  const [solutionsLoading, setSolutionsLoading] = useState(false);
  const limit = typeof freeLimit === "number" ? freeLimit : FREE_LIMIT;
  const used = Math.min(solvedCount, limit);
  const remaining = isPro ? null : (typeof availableRequests === "number" ? availableRequests : limit - used);
  const days = daysUntilUpdate ?? 0;

  useEffect(() => {
    if (!telegramId) return;
    setSolutionsLoading(true);
    fetch("/api/solutions", { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : { solutions: [] }))
      .then((data) => setSolutions(data.solutions || []))
      .catch(() => setSolutions([]))
      .finally(() => setSolutionsLoading(false));
  }, [telegramId]);

  let hint = "Отправьте /start боту и нажмите «📚 Открыть TestAI» — счётчик привяжется автоматически.";
  if (debugInfo) {
    const d = debugInfo;
    const parts = [];
    if (!d.init_data_received) parts.push("initData на сервер не пришёл");
    else if (!d.validation_passed) parts.push(`initData пришёл (${d.init_data_len} символов), но проверка не прошла — проверьте TELEGRAM_BOT_TOKEN в .env`);
    else parts.push("Проверка пройдена, но пользователь не определён");
    if (!d.bot_token_set) parts.push("TELEGRAM_BOT_TOKEN не задан");
    hint = parts.join(". ");
  }

  return (
    <section className="profile-card glass">
      {!telegramId && (
        <div className="status status--error" style={{ marginBottom: 16 }}>
          <span className="status-dot" />
          <span>{hint}</span>
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
            <div>Использовано {used} из {limit}</div>
            <div>Обновление через {days} {days === 1 ? "день" : days < 5 ? "дня" : "дней"}</div>
          </div>
          <div className="profile-limit-bar-wrap">
            <div
              className="profile-limit-bar-fill"
              style={{ width: `${Math.min(100, limit ? (used / limit) * 100 : 0)}%` }}
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

      {telegramId && (
        <div className="profile-history-block">
          <h3 className="profile-history-title">История задач</h3>
          {solutionsLoading ? (
            <div className="profile-history-loading">Загрузка…</div>
          ) : solutions.length === 0 ? (
            <div className="profile-history-empty">Пока нет сохранённых решений. Решай задачи — они появятся здесь на 12 часов.</div>
          ) : (
            <ul className="profile-history-list">
              {solutions.map((s, idx) => (
                <li key={s.id} className="profile-history-item">
                  <span className="profile-history-icon" aria-hidden data-type={idx % 3}>{["📐", "⚡", "📖"][idx % 3]}</span>
                  <span className="profile-history-desc">{s.task_text || `Решение от ${formatSolutionDate(s.created_at)}`}</span>
                  <a href={`/solution/${s.id}`} target="_blank" rel="noopener noreferrer" className="profile-history-btn">Посмотреть</a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          method: methodId,
          init_data: initData || undefined,
          auth_token: getAuthToken() || undefined,
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
  const [debugInfo, setDebugInfo] = useState(null);
  const [freeLimit, setFreeLimit] = useState(10);

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
    const params = new URLSearchParams(window.location.search || "");
    const tgAuth = params.get("tg_auth");
    if (!tgAuth) return;
    fetch("/api/auth/telegram", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: tgAuth }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.auth_token) {
          setAuthToken(data.auth_token);
          setTelegramId(data.telegram_id);
          setSolvedCount(data.requests_used || 0);
          setAvailableRequests(data.remaining ?? 10);
          setIsPro(data.is_pro || false);
          setDisplayName(data.first_name || data.username || "Ученик");
          setDebugInfo(null);
          if (typeof data.days_until_update === "number") setDaysUntilUpdate(data.days_until_update);
          if (typeof data.free_limit === "number") setFreeLimit(data.free_limit);
        }
      })
      .finally(() => {
        const u = new URL(window.location.href);
        u.searchParams.delete("tg_auth");
        window.history.replaceState({}, "", u.pathname + (u.search || "") + (u.hash || ""));
      });
  }, []);

  useEffect(() => {
    if (new URLSearchParams(window.location.search || "").get("tg_auth")) return;
    const init = () => {
      const initData = getInitData();
      const authTok = getAuthToken();
      const base = initData ? `/api/me?init_data=${encodeURIComponent(initData)}&debug=1` : "/api/me?debug=1";
      const headers = { "X-Telegram-Init-Data": initData };
      if (authTok) headers["X-Auth-Token"] = authTok;
      return fetch(base, { headers })
        .then(r => r.json())
        .then(data => {
          if (data.telegram_id) {
            setTelegramId(data.telegram_id);
            setSolvedCount(data.requests_used || 0);
            setDebugInfo(null);
            if (typeof data.days_until_update === "number") setDaysUntilUpdate(data.days_until_update);
          } else {
            setSolvedCount(0);
            setDebugInfo(data.debug || null);
          }
          setAvailableRequests(data.remaining ?? 10);
          setIsPro(data.is_pro || false);
          if (typeof data.free_limit === "number") setFreeLimit(data.free_limit);
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
    const authTok = getAuthToken();
    const base = initData ? `/api/me?init_data=${encodeURIComponent(initData)}&debug=1` : "/api/me?debug=1";
    const headers = { "X-Telegram-Init-Data": initData };
    if (authTok) headers["X-Auth-Token"] = authTok;
    fetch(base, { headers })
      .then(r => r.json())
      .then(data => {
        if (data.telegram_id) {
          setTelegramId(data.telegram_id);
          setSolvedCount(data.requests_used || 0);
          setDebugInfo(null);
          if (typeof data.days_until_update === "number") setDaysUntilUpdate(data.days_until_update);
        } else {
          setSolvedCount(0);
          setDebugInfo(data.debug || null);
        }
        setAvailableRequests(data.remaining ?? 10);
        setIsPro(data.is_pro || false);
        if (typeof data.free_limit === "number") setFreeLimit(data.free_limit);
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text.trim() || null,
          detail: mode === "short" ? "short" : "detailed",
          image_base64: imageBase64,
          telegram_id: telegramId,
          init_data: getInitData() || undefined,
          auth_token: getAuthToken() || undefined,
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

      const taskLabel = text.trim() ? text.trim() : "Задача по изображению";
      const solResp = await fetch("/api/solution", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          answer: answerText,
          task_text: taskLabel,
          init_data: getInitData() || undefined,
          auth_token: getAuthToken() || undefined,
        }),
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
          {Object.entries(TABS).map(([id, { label }]) => (
            <button
              key={id}
              type="button"
              className={`tab-item ${effectiveTab === id ? "tab-item--active" : ""}`}
              onClick={() => setEffectiveTab(id)}
            >
              <span className="tab-icon">{TAB_ICONS[id]}</span>
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
              freeLimit={freeLimit}
              isPro={isPro}
              displayName={displayName}
              daysUntilUpdate={daysUntilUpdate}
              telegramId={telegramId}
              debugInfo={debugInfo}
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


