import { useAuth } from '../auth/AuthContext'
import { RecentTransactions } from '../components/RecentTransactions'
import { UpcomingEvents } from '../components/UpcomingEvents'

export function OverviewPage() {
  const { user } = useAuth()
  const firstName = (user?.full_name ?? '').split(' ')[0] || 'друже'

  return (
    <>
      <section className="page-hero">
        <div>
          <p className="page-hero__eyebrow">Особистий кабінет</p>
          <h1 className="page-hero__title">Привіт, {firstName}! 👋</h1>
          <p className="page-hero__lead">
            Підключи канали, налаштуй часовий пояс і керуй фінансами та
            розкладом просто з повідомлень.
          </p>
        </div>
        {user?.google_spreadsheet_id && (
          <a
            className="page-hero__cta"
            href={`https://docs.google.com/spreadsheets/d/${user.google_spreadsheet_id}/edit`}
            target="_blank"
            rel="noreferrer"
          >
            <span aria-hidden="true">📊</span>
            <span>Відкрити Google Sheet</span>
          </a>
        )}
      </section>

      <div className="page-grid">
        <div className="page-grid__col">
          <RecentTransactions />
        </div>
        <div className="page-grid__col">
          <UpcomingEvents />
        </div>
      </div>
    </>
  )
}
