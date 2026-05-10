import { NavLink, Link } from 'react-router-dom'
import {
  Home,
  Wallet,
  Calendar,
  Settings,
  LogOut,
  Sparkles,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { ThemeToggle } from '../theme/ThemeToggle'
import './Sidebar.css'

interface NavItem {
  to: string
  label: string
  icon: typeof Home
  end?: boolean
}

const NAV: NavItem[] = [
  { to: '/', label: 'Огляд', icon: Home, end: true },
  { to: '/finance', label: 'Кошти', icon: Wallet },
  { to: '/calendar', label: 'Календар', icon: Calendar },
  { to: '/settings', label: 'Налаштування', icon: Settings },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const initial = (user?.full_name || user?.email || '?').charAt(0).toUpperCase()

  return (
    <aside className="sidebar" aria-label="Основна навігація">
      <Link to="/" className="sidebar__brand">
        <span className="sidebar__brand-mark" aria-hidden="true">
          <Sparkles size={18} strokeWidth={2.25} />
        </span>
        <span className="sidebar__brand-name">WalletCalBot</span>
      </Link>

      <nav className="sidebar__nav">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end ?? false}
            className={({ isActive }) =>
              `sidebar__link${isActive ? ' sidebar__link--active' : ''}`
            }
          >
            <Icon size={18} strokeWidth={2} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar__footer">
        <ThemeToggle />

        {user && (
          <div className="sidebar__profile">
            {user.picture_url ? (
              <img src={user.picture_url} alt="" className="sidebar__avatar" />
            ) : (
              <div className="sidebar__avatar sidebar__avatar--initial">
                {initial}
              </div>
            )}
            <div className="sidebar__profile-text">
              <div className="sidebar__profile-name">
                {user.full_name ?? 'Користувач'}
              </div>
              {user.email && (
                <div className="sidebar__profile-email">{user.email}</div>
              )}
            </div>
            <button
              type="button"
              className="sidebar__logout"
              onClick={logout}
              aria-label="Вийти"
              title="Вийти"
            >
              <LogOut size={16} strokeWidth={2} />
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}
