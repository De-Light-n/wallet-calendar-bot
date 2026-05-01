import { useTheme, type ThemeMode } from './ThemeContext'
import './ThemeToggle.css'

const LABELS: Record<ThemeMode, string> = {
  light: 'Світла',
  dark: 'Темна',
  system: 'Системна',
}

const ICONS: Record<ThemeMode, string> = {
  light: '☀️',
  dark: '🌙',
  system: '💻',
}

export function ThemeToggle() {
  const { mode, cycle } = useTheme()

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={cycle}
      title={`Тема: ${LABELS[mode]} — натисни щоб змінити`}
      aria-label={`Перемкнути тему. Зараз: ${LABELS[mode]}`}
    >
      <span className="theme-toggle__icon" aria-hidden="true">
        {ICONS[mode]}
      </span>
      <span className="theme-toggle__label">{LABELS[mode]}</span>
    </button>
  )
}
