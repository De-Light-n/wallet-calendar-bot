import { useAuth } from '../auth/AuthContext'
import { ChatPanel } from '../components/ChatPanel'
import { RecentTransactions } from '../components/RecentTransactions'
import { UpcomingEvents } from '../components/UpcomingEvents'

export function OverviewPage() {
  const { user } = useAuth()
  const firstName = (user?.full_name ?? '').split(' ')[0] || 'друже'

  return (
    <>
      <section className="overview-hero">
        <p className="overview-hero__eyebrow">Особистий асистент</p>
        <h1 className="overview-hero__title">
          Привіт, <span className="overview-hero__name">{firstName}</span>! 👋
        </h1>
        <p className="overview-hero__lead">
          Пиши природною мовою — я запишу витрату, створю подію в календарі або
          покажу те, що вже там є. Працює і тут, і в Telegram, Slack, Discord.
        </p>
      </section>

      <ChatPanel />

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
