import { createContext, useContext, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'

export interface ChannelLink {
  channel: string
  external_user_id: string
  username: string | null
  display_name: string | null
}

export interface CurrentUser {
  id: number
  email: string | null
  full_name: string | null
  picture_url: string | null
  timezone: string
  base_currency: string
  google_spreadsheet_id: string | null
  spreadsheet_schema_version: number
  enabled_channels: string[]
  channels: ChannelLink[]
}

interface AuthContextValue {
  user: CurrentUser | null
  isLoading: boolean
  isAuthenticated: boolean
  refresh: () => void
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const query = useQuery<CurrentUser | null>({
    queryKey: ['auth', 'me'],
    queryFn: async () => {
      try {
        return await api.get<CurrentUser>('/auth/me')
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return null
        throw err
      }
    },
    retry: false,
    staleTime: 30_000,
  })

  const value: AuthContextValue = {
    user: query.data ?? null,
    isLoading: query.isLoading,
    isAuthenticated: !!query.data,
    refresh: () => qc.invalidateQueries({ queryKey: ['auth', 'me'] }),
    logout: async () => {
      await api.post('/auth/logout')
      qc.setQueryData(['auth', 'me'], null)
      qc.invalidateQueries()
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
