import { useAuth } from '../auth/AuthContext'
import { ThemeToggle } from '../theme/ThemeToggle'
import './UserHeader.css'

export function UserHeader() {
  const { user, logout } = useAuth()
  if (!user) return null

  const initial = (user.full_name || user.email || '?').charAt(0).toUpperCase()

  return (
    <header className="user-header">
      <div className="user-header__inner">
        <a href="/" className="brand">
          <span className="brand__logo" aria-hidden="true">💼</span>
          <span className="brand__name">WalletCalBot</span>
        </a>

        <div className="user-header__actions">
          <ThemeToggle />
          <div className="profile">
            {user.picture_url ? (
              <img src={user.picture_url} alt="" className="avatar" />
            ) : (
              <div className="avatar avatar--initial">{initial}</div>
            )}
            <div className="profile__text">
              <div className="profile__name">
                {user.full_name ?? 'Користувач'}
              </div>
              {user.email && <div className="profile__email">{user.email}</div>}
            </div>
          </div>
          <button className="logout-btn" onClick={logout}>
            Вийти
          </button>
        </div>
      </div>
    </header>
  )
}
