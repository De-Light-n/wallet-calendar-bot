import { Outlet } from 'react-router-dom'
import { NavTabs } from '../components/NavTabs'
import { UserHeader } from '../components/UserHeader'
import './AppLayout.css'

export function AppLayout() {
  return (
    <>
      <UserHeader />
      <NavTabs />
      <main className="app-main">
        <Outlet />
      </main>
    </>
  )
}
