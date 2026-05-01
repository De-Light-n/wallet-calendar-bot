import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

interface ThemeContextValue {
  /** What the user picked: 'light', 'dark', or 'system'. */
  mode: ThemeMode
  /** What's actually applied right now: 'light' or 'dark'. */
  resolved: ResolvedTheme
  /** Set explicit mode. */
  setMode: (mode: ThemeMode) => void
  /** Convenience: cycle light → dark → system → light. */
  cycle: () => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

const STORAGE_KEY = 'wcb-theme'
const DEFAULT_MODE: ThemeMode = 'light' // user preference: default white/light

function readStoredMode(): ThemeMode {
  if (typeof window === 'undefined') return DEFAULT_MODE
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  return DEFAULT_MODE
}

function systemPrefersDark(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === 'system') return systemPrefersDark() ? 'dark' : 'light'
  return mode
}

function applyTheme(resolved: ResolvedTheme) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = resolved
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(() => readStoredMode())
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    resolveTheme(readStoredMode()),
  )

  // Apply on mount + whenever the resolved value changes.
  useEffect(() => {
    applyTheme(resolved)
  }, [resolved])

  // Re-resolve when the user picks a new mode.
  useEffect(() => {
    setResolved(resolveTheme(mode))
  }, [mode])

  // When the user picks 'system', listen to OS-level changes and update live.
  useEffect(() => {
    if (mode !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => setResolved(media.matches ? 'dark' : 'light')
    media.addEventListener('change', handler)
    return () => media.removeEventListener('change', handler)
  }, [mode])

  const setMode = useCallback((next: ThemeMode) => {
    setModeState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // localStorage can be blocked (private mode, embedded contexts) — silent fallback.
    }
  }, [])

  const cycle = useCallback(() => {
    setMode(mode === 'light' ? 'dark' : mode === 'dark' ? 'system' : 'light')
  }, [mode, setMode])

  const value = useMemo<ThemeContextValue>(
    () => ({ mode, resolved, setMode, cycle }),
    [mode, resolved, setMode, cycle],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
