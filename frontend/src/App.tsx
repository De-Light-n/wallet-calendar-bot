import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAuth, AuthProvider } from './auth/AuthContext'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'

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
  return isAuthenticated ? <DashboardPage /> : <LoginPage />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Root />
      </AuthProvider>
    </QueryClientProvider>
  )
}
