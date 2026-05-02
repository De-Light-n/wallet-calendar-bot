import { NavLink } from 'react-router-dom'
import './NavTabs.css'

interface Tab {
  to: string
  label: string
  icon: string
  end?: boolean
}

const TABS: Tab[] = [
  { to: '/', label: 'Огляд', icon: '🏠', end: true },
  { to: '/finance', label: 'Кошти', icon: '💰' },
  { to: '/calendar', label: 'Календар', icon: '📅' },
  { to: '/settings', label: 'Налаштування', icon: '⚙️' },
]

export function NavTabs() {
  return (
    <nav className="nav-tabs" aria-label="Основна навігація">
      <div className="nav-tabs__inner">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end ?? false}
            className={({ isActive }) =>
              `nav-tab${isActive ? ' nav-tab--active' : ''}`
            }
          >
            <span className="nav-tab__icon" aria-hidden="true">
              {tab.icon}
            </span>
            <span className="nav-tab__label">{tab.label}</span>
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
