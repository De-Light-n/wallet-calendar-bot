import { Outlet } from 'react-router-dom'
import { Sidebar } from '../components/Sidebar'
import './AppLayout.css'

export function AppLayout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <div className="app-main__inner">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
