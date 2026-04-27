export function LoginPage() {
  const params = new URLSearchParams(window.location.search)
  const authError = params.get('auth_error')

  return (
    <div className="min-h-svh bg-white dark:bg-gray-950 text-gray-900 dark:text-gray-100 flex flex-col">
      {/* ── Navbar ── */}
      <nav className="border-b border-gray-100 dark:border-gray-800 shrink-0">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <span className="font-semibold text-lg tracking-tight">💼 WalletCalBot</span>
          <a
            href="/auth/google/init"
            className="text-sm font-medium text-purple-600 dark:text-purple-400 hover:underline"
          >
            Увійти
          </a>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="py-24 px-6 text-center">
        <div className="max-w-3xl mx-auto">
          <div className="inline-flex items-center gap-2 bg-purple-50 dark:bg-purple-950 text-purple-700 dark:text-purple-300 text-sm font-medium px-4 py-1.5 rounded-full mb-8 border border-purple-100 dark:border-purple-900">
            🤖 AI-асистент для Telegram
          </div>

          <h1 className="text-5xl md:text-6xl font-bold tracking-tight mb-6 leading-[1.1] text-gray-900 dark:text-white">
            Фінанси і розклад —<br />
            <span className="text-purple-600 dark:text-purple-400">просто напиши</span>
          </h1>

          <p className="text-xl text-gray-500 dark:text-gray-400 mb-10 max-w-xl mx-auto leading-relaxed">
            Витратив гроші або маєш зустріч? Пиши або говори в&nbsp;Telegram —
            бот сам запише в Google&nbsp;Sheets і Calendar.
          </p>

          {authError && (
            <div className="max-w-sm mx-auto mb-6 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 rounded-xl px-5 py-4 text-sm">
              Не вдалось увійти: {authError}. Спробуй ще раз.
            </div>
          )}

          <a
            href="/auth/google/init"
            className="inline-flex items-center gap-3 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 border border-gray-200 dark:border-gray-700 px-6 py-3.5 rounded-xl font-medium text-base shadow-sm hover:shadow-md transition-shadow"
          >
            <GoogleIcon />
            Увійти через Google
          </a>

          <p className="text-sm text-gray-400 mt-4">
            Ми запитаємо доступ до Calendar, Sheets та Drive (тільки до файлів бота)
          </p>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="py-20 px-6 bg-gray-50 dark:bg-gray-900">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-3 text-gray-900 dark:text-white">
            Що вміє бот?
          </h2>
          <p className="text-center text-gray-500 dark:text-gray-400 mb-12 max-w-md mx-auto">
            Природне спілкування — без форм, команд і таблиць вручну
          </p>
          <div className="grid md:grid-cols-3 gap-6">
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
      <section className="py-20 px-6">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-12 text-gray-900 dark:text-white">
            Як підключитись?
          </h2>
          <div className="grid md:grid-cols-3 gap-8">
            <Step
              num={1}
              title="Зареєструйся"
              desc="Увійди через Google — дозволяєш доступ до Calendar, Sheets і Drive."
            />
            <Step
              num={2}
              title="Отримай код"
              desc="В дашборді натисни «Підключити Telegram» і скопіюй одноразовий код."
            />
            <Step
              num={3}
              title="Напиши боту"
              desc="Відкрий бот в Telegram і надішли /link ТВІЙ_КОД — готово!"
            />
          </div>
        </div>
      </section>

      {/* ── CTA banner ── */}
      <section className="py-20 px-6 bg-purple-600 dark:bg-purple-900 text-white text-center">
        <h2 className="text-3xl font-bold mb-3">Готовий спробувати?</h2>
        <p className="text-purple-100 mb-8 text-lg">Реєстрація займає менше хвилини</p>
        <a
          href="/auth/google/init"
          className="inline-flex items-center gap-3 bg-white text-purple-700 px-7 py-3.5 rounded-xl font-semibold text-base hover:bg-purple-50 transition-colors shadow-lg"
        >
          <GoogleIcon />
          Почати безплатно
        </a>
      </section>

      {/* ── Footer ── */}
      <footer className="py-8 px-6 border-t border-gray-100 dark:border-gray-800 text-center text-sm text-gray-400 mt-auto">
        <p>WalletCalBot — AI-асистент для Google Workspace та Telegram</p>
      </footer>
    </div>
  )
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.258h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.583-5.036-3.71H.957v2.332A8.997 8.997 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" />
      <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" />
    </svg>
  )
}

function FeatureCard({ icon, title, desc }: { icon: string; title: string; desc: string }) {
  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-2xl p-6 shadow-sm">
      <div className="text-3xl mb-4">{icon}</div>
      <h3 className="font-semibold text-lg mb-2 text-gray-900 dark:text-white">{title}</h3>
      <p className="text-gray-500 dark:text-gray-400 text-sm leading-relaxed">{desc}</p>
    </div>
  )
}

function Step({ num, title, desc }: { num: number; title: string; desc: string }) {
  return (
    <div className="text-center">
      <div className="w-12 h-12 bg-purple-600 text-white rounded-full flex items-center justify-center text-xl font-bold mx-auto mb-4">
        {num}
      </div>
      <h3 className="font-semibold text-lg mb-2 text-gray-900 dark:text-white">{title}</h3>
      <p className="text-gray-500 dark:text-gray-400 text-sm leading-relaxed">{desc}</p>
    </div>
  )
}
