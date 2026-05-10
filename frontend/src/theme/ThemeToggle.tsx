import { Sun, Moon, Monitor } from 'lucide-react'
import { useTheme, type ThemeMode } from './ThemeContext'
import './ThemeToggle.css'

const LABELS: Record<ThemeMode, string> = {
  light: 'Світла',
  dark: 'Темна',
  system: 'Системна',
}

const ICONS: Record<ThemeMode, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
}

export function ThemeToggle() {
  const { mode, cycle } = useTheme()
  const Icon = ICONS[mode]

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={cycle}
      title={`Тема: ${LABELS[mode]} — натисни щоб змінити`}
      aria-label={`Перемкнути тему. Зараз: ${LABELS[mode]}`}
    >
      <Icon size={15} strokeWidth={2} aria-hidden="true" />
      <span className="theme-toggle__label">{LABELS[mode]}</span>
    </button>
  )
}
