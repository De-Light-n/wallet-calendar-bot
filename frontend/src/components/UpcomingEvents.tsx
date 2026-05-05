import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import './Card.css'

interface CalendarEvent {
  id: string
  title: string
  start: string | null
  end: string | null
  location: string | null
  description: string | null
  html_link: string | null
}

function formatStart(iso: string | null): string {
  if (!iso) return ''
  // All-day events come back as "YYYY-MM-DD"; timed ones as full ISO.
  if (iso.length === 10) return iso
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export function UpcomingEvents() {
  const { data, isLoading, error } = useQuery<{ items: CalendarEvent[] }>({
    queryKey: ['calendar', 'upcoming'],
    queryFn: () => api.get('/api/me/calendar/upcoming?limit=10'),
    staleTime: 60_000,
  })

  return (
    <section className="card">
      <h2>📅 Найближчі події</h2>
      <p className="card-subtitle">Найближчі 10 подій з Google Calendar</p>

      {isLoading && <div className="muted">Завантажую…</div>}
      {error && <div className="muted">Не вдалось завантажити.</div>}

      {data && data.items.length === 0 && (
        <div className="empty">
          Подій немає. Напиши боту: <em>«Зустріч завтра о 14:00»</em>
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="list">
          {data.items.map((ev) => (
            <li key={ev.id}>
              <span>
                <span className="list-item__title">
                  {ev.title || '(без назви)'}
                  {ev.location && (
                    <span className="list-item__inline"> · {ev.location}</span>
                  )}
                </span>
                <span className="list-item__sub">{formatStart(ev.start)}</span>
              </span>
              {ev.html_link && (
                <a
                  href={ev.html_link}
                  target="_blank"
                  rel="noreferrer"
                  className="list-item__link"
                  aria-label="Відкрити подію в Google Calendar"
                >
                  →
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
