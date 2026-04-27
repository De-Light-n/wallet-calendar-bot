import { useAuth } from '../auth/AuthContext'
import './UserHeader.css'

export function UserHeader() {
  const { user, logout } = useAuth()
  if (!user) return null

  return (
    <header className="user-header">
      <div className="profile">
        {user.picture_url && (
          <img src={user.picture_url} alt="" className="avatar" />
        )}
        <div>
          <div className="name">{user.full_name ?? 'Користувач'}</div>
          {user.email && <div className="email">{user.email}</div>}
        </div>
      </div>
      <button className="logout-btn" onClick={logout}>
        Вийти
      </button>
    </header>
  )
}
