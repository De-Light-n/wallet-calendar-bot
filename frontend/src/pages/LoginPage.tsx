import { ThemeToggle } from '../theme/ThemeToggle'
import './LoginPage.css'

export function LoginPage() {
  const params = new URLSearchParams(window.location.search)
  const authError = params.get('auth_error')

  return (
    <div className="landing">
      {/* ── Navbar ── */}
      <nav className="landing-nav">
        <div className="landing-nav__inner">
          <a href="/" className="brand">
            <span className="brand__logo" aria-hidden="true">💼</span>
            <span className="brand__name">WalletCalBot</span>
          </a>
          <div className="landing-nav__actions">
            <ThemeToggle />
            <a href="/auth/google/init" className="landing-nav__login">
              Увійти
            </a>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="hero">
        <div className="hero__inner">
          <div className="hero__pill">🤖 AI-асистент для месенджерів</div>

          <h1 className="hero__title">
            Фінанси і розклад —<br />
            <span className="hero__title-accent">просто напиши</span>
          </h1>

          <p className="hero__lead">
            Витратив гроші або маєш зустріч? Пиши або говори в Telegram чи
            Slack — бот сам запише в Google&nbsp;Sheets і створить подію в
            Google&nbsp;Calendar.
          </p>

          {authError && (
            <div className="auth-error">
              Не вдалось увійти: {authError}. Спробуй ще раз.
            </div>
          )}

          <a href="/auth/google/init" className="google-btn">
            <GoogleIcon />
            Увійти через Google
          </a>

          <p className="hero__hint">
            Ми запитаємо доступ до Calendar, Sheets та Drive (тільки до файлів
            бота)
          </p>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="section section--soft">
        <div className="section__inner">
          <h2 className="section__title">Що вміє бот?</h2>
          <p className="section__lead">
            Природне спілкування — без форм, команд і таблиць вручну
          </p>
          <div className="features">
            <FeatureCard
              icon="💳"
              title="Облік витрат"
              desc="«Купив каву за 85 грн» — бот запише дату, суму, категорію та опис у твою таблицю Google Sheets автоматично."
            />
            <FeatureCard
              icon="📅"
              title="Google Calendar"
              desc="«Нарада з командою в п'ятницю о 10:00» — бот створить подію і налаштує нагадування за тебе."
            />
            <FeatureCard
              icon="🎤"
              title="Голосові повідомлення"
              desc="Не хочеш писати? Надішли голосове — бот розшифрує і виконає завдання, як ти сказав."
            />
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="section">
        <div className="section__inner section__inner--narrow">
          <h2 className="section__title">Як підключитись?</h2>
          <div className="steps">
            <Step
              num={1}
              title="Зареєструйся"
              desc="Увійди через Google — дозволяєш доступ до Calendar, Sheets і Drive."
            />
            <Step
              num={2}
              title="Отримай код"
              desc="В дашборді натисни «Згенерувати код» і скопіюй одноразовий код."
            />
            <Step
              num={3}
              title="Напиши боту"
              desc="Відкрий бот в Telegram (або Slack) і надішли /link ТВІЙ_КОД — готово!"
            />
          </div>
        </div>
      </section>

      {/* ── CTA banner ── */}
      <section className="cta">
        <h2 className="cta__title">Готовий спробувати?</h2>
        <p className="cta__lead">Реєстрація займає менше хвилини</p>
        <a href="/auth/google/init" className="cta__btn">
          <GoogleIcon />
          Почати безплатно
        </a>
      </section>

      {/* ── Footer ── */}
      <footer className="landing-footer">
        <p>WalletCalBot — AI-асистент для Google Workspace та месенджерів</p>
      </footer>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.583-5.036-3.71H.957v2.332A8.997 8.997 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"
      />
    </svg>
  )
}

function FeatureCard({
  icon,
  title,
  desc,
}: {
  icon: string
  title: string
  desc: string
}) {
  return (
    <div className="feature">
      <div className="feature__icon">{icon}</div>
      <h3 className="feature__title">{title}</h3>
      <p className="feature__desc">{desc}</p>
    </div>
  )
}

function Step({
  num,
  title,
  desc,
}: {
  num: number
  title: string
  desc: string
}) {
  return (
    <div className="step">
      <div className="step__num">{num}</div>
      <h3 className="step__title">{title}</h3>
      <p className="step__desc">{desc}</p>
    </div>
  )
}
