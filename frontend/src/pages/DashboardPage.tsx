import { ConnectTelegram } from '../components/ConnectTelegram'
import { RecentTransactions } from '../components/RecentTransactions'
import { TimezoneSetting } from '../components/TimezoneSetting'
import { UpcomingEvents } from '../components/UpcomingEvents'
import { UserHeader } from '../components/UserHeader'
import './DashboardPage.css'

export function DashboardPage() {
  return (
    <>
      <UserHeader />
      <main className="dashboard">
        <div className="grid">
          <ConnectTelegram />
          <TimezoneSetting />
          <RecentTransactions />
          <UpcomingEvents />
        </div>
      </main>
    </>
  )
}
