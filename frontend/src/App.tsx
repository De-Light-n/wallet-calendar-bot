import { lazy, Suspense } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth, AuthProvider } from './auth/AuthContext'
import { LoginPage } from './pages/LoginPage'
import { AppLayout } from './pages/AppLayout'
import { OverviewPage } from './pages/OverviewPage'
import { SettingsPage } from './pages/SettingsPage'

// Heavy pages loaded on-demand: FinancePage pulls in recharts (~370KB),
// CalendarPage owns the month-grid component which is also non-trivial.
const FinancePage = lazy(() =>
  import('./pages/FinancePage').then((m) => ({ default: m.FinancePage })),
)
const CalendarPage = lazy(() =>
  import('./pages/CalendarPage').then((m) => ({ default: m.CalendarPage })),
)

function PageFallback() {
  return (
    <div style={{ display: 'grid', placeItems: 'center', padding: 64 }}>
      Завантажую…
    </div>
  )
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
})

function Root() {
  const { isLoading, isAuthenticated } = useAuth()
  if (isLoading) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', minHeight: '100svh' }}>
        Завантаження…
      </div>
    )
  }
  if (!isAuthenticated) {
    return <LoginPage />
  }
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="finance" element={<FinancePage />} />
          <Route path="calendar" element={<CalendarPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Root />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
