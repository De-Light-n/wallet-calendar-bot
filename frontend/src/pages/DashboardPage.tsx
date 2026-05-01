import { useAuth } from '../auth/AuthContext'
import { ConnectDiscord } from '../components/ConnectDiscord'
import { ConnectSlack } from '../components/ConnectSlack'
import { ConnectTelegram } from '../components/ConnectTelegram'
import { RecentTransactions } from '../components/RecentTransactions'
import { TimezoneSetting } from '../components/TimezoneSetting'
import { UpcomingEvents } from '../components/UpcomingEvents'
import { UserHeader } from '../components/UserHeader'
import './DashboardPage.css'

export function DashboardPage() {
  const { user } = useAuth()
  const firstName = (user?.full_name ?? '').split(' ')[0] || 'друже'
  const enabled = user?.enabled_channels ?? []

  return (
    <>
      <UserHeader />
      <main className="dashboard">
        <section className="dashboard-hero">
          <div>
            <p className="dashboard-hero__eyebrow">Особистий кабінет</p>
            <h1 className="dashboard-hero__title">
              Привіт, {firstName}! 👋
            </h1>
            <p className="dashboard-hero__lead">
              Підключи канали, налаштуй часовий пояс і керуй фінансами та
              розкладом просто з повідомлень.
            </p>
          </div>
          {user?.google_spreadsheet_id && (
            <a
              className="dashboard-hero__cta"
              href={`https://docs.google.com/spreadsheets/d/${user.google_spreadsheet_id}/edit`}
              target="_blank"
              rel="noreferrer"
            >
              <span aria-hidden="true">📊</span>
              <span>Відкрити Google Sheet</span>
            </a>
          )}
        </section>

        <div className="dashboard-grid">
          <div className="dashboard-grid__col">
            {enabled.includes('telegram') && <ConnectTelegram />}
            {enabled.includes('slack') && <ConnectSlack />}
            {enabled.includes('discord') && <ConnectDiscord />}
            <TimezoneSetting />
          </div>
          <div className="dashboard-grid__col">
            <RecentTransactions />
            <UpcomingEvents />
          </div>
        </div>
      </main>
    </>
  )
}
