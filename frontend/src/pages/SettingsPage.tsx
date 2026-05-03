import { useAuth } from '../auth/AuthContext'
import { BaseCurrencySetting } from '../components/BaseCurrencySetting'
import { ConnectDiscord } from '../components/ConnectDiscord'
import { ConnectSlack } from '../components/ConnectSlack'
import { ConnectTelegram } from '../components/ConnectTelegram'
import { TimezoneSetting } from '../components/TimezoneSetting'

export function SettingsPage() {
  const { user } = useAuth()
  const enabled = user?.enabled_channels ?? []

  return (
    <>
      <section className="page-hero">
        <div>
          <p className="page-hero__eyebrow">Налаштування</p>
          <h1 className="page-hero__title">Налаштування ⚙️</h1>
          <p className="page-hero__lead">
            Керуй підключеними каналами, часовим поясом і пов'язаними сервісами.
          </p>
        </div>
      </section>

      <div className="page-grid">
        <div className="page-grid__col">
          {enabled.includes('telegram') && <ConnectTelegram />}
          {enabled.includes('slack') && <ConnectSlack />}
          {enabled.includes('discord') && <ConnectDiscord />}
        </div>
        <div className="page-grid__col">
          <TimezoneSetting />
          <BaseCurrencySetting />
        </div>
      </div>
    </>
  )
}
