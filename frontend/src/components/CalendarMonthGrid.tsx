import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import './CalendarMonthGrid.css'

interface CalendarEvent {
  id: string
  title: string
  start: string | null
  end: string | null
  location: string | null
  description: string | null
  html_link: string | null
}

const MONTH_NAMES_UK = [
  'Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень',
  'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень',
]

const WEEKDAY_LABELS_UK = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']

function ymd(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function eventDateKey(iso: string | null): string | null {
  if (!iso) return null
  if (iso.length === 10) return iso // all-day "YYYY-MM-DD"
  try {
    const d = new Date(iso)
    return ymd(d)
  } catch {
    return null
  }
}

function formatTime(iso: string | null): string {
  if (!iso || iso.length === 10) return ''
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}

// Builds a 6-row × 7-col grid covering the month, padded with adjacent-month
// days. Monday-first layout to match Ukrainian calendar convention.
function buildMonthGrid(viewYear: number, viewMonth: number): Date[] {
  const firstOfMonth = new Date(viewYear, viewMonth, 1)
  // JS getDay: 0=Sun..6=Sat. Convert to Mon=0..Sun=6.
  const offsetMon = (firstOfMonth.getDay() + 6) % 7
  const start = new Date(viewYear, viewMonth, 1 - offsetMon)
  const cells: Date[] = []
  for (let i = 0; i < 42; i += 1) {
    cells.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i))
  }
  return cells
}

export function CalendarMonthGrid() {
  const today = useMemo(() => new Date(), [])
  const [viewDate, setViewDate] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1))
  const [selectedDate, setSelectedDate] = useState<string>(ymd(today))

  const viewYear = viewDate.getFullYear()
  const viewMonth = viewDate.getMonth()

  const cells = useMemo(() => buildMonthGrid(viewYear, viewMonth), [viewYear, viewMonth])

  // Fetch events covering the entire visible grid (not just the month) so that
  // padded prev/next-month days also show markers.
  const rangeFrom = ymd(cells[0])
  const rangeTo = ymd(cells[cells.length - 1])

  const { data, isLoading, error } = useQuery<{ items: CalendarEvent[] }>({
    queryKey: ['calendar', 'range', rangeFrom, rangeTo],
    queryFn: () =>
      api.get(`/api/me/calendar/range?from=${rangeFrom}&to=${rangeTo}`),
    staleTime: 60_000,
  })

  // Group events by their start date for fast lookup per cell.
  const eventsByDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const ev of data?.items ?? []) {
      const key = eventDateKey(ev.start)
      if (!key) continue
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(ev)
    }
    return map
  }, [data])

  const selectedEvents = eventsByDay.get(selectedDate) ?? []
  const todayKey = ymd(today)

  const goPrev = () => setViewDate(new Date(viewYear, viewMonth - 1, 1))
  const goNext = () => setViewDate(new Date(viewYear, viewMonth + 1, 1))
  const goToday = () => {
    const d = new Date()
    setViewDate(new Date(d.getFullYear(), d.getMonth(), 1))
    setSelectedDate(ymd(d))
  }

  return (
    <section className="card cal-card">
      <header className="cal-header">
        <h2>
          {MONTH_NAMES_UK[viewMonth]} {viewYear}
        </h2>
        <div className="cal-nav">
          <button className="cal-nav__btn" onClick={goPrev} aria-label="Попередній місяць">
            ‹
          </button>
          <button className="cal-nav__btn cal-nav__today" onClick={goToday}>
            Сьогодні
          </button>
          <button className="cal-nav__btn" onClick={goNext} aria-label="Наступний місяць">
            ›
          </button>
        </div>
      </header>

      {error && <div className="muted">Не вдалось завантажити події.</div>}

      <div className="cal-grid">
        <div className="cal-weekdays">
          {WEEKDAY_LABELS_UK.map((w) => (
            <div key={w} className="cal-weekday">
              {w}
            </div>
          ))}
        </div>
        <div className="cal-days">
          {cells.map((d) => {
            const key = ymd(d)
            const inMonth = d.getMonth() === viewMonth
            const isToday = key === todayKey
            const isSelected = key === selectedDate
            const eventsHere = eventsByDay.get(key) ?? []
            return (
              <button
                key={key}
                type="button"
                className={[
                  'cal-day',
                  inMonth ? '' : 'cal-day--out',
                  isToday ? 'cal-day--today' : '',
                  isSelected ? 'cal-day--selected' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => setSelectedDate(key)}
              >
                <span className="cal-day__num">{d.getDate()}</span>
                {eventsHere.length > 0 && (
                  <span className="cal-day__dots" aria-label={`${eventsHere.length} подій`}>
                    {eventsHere.slice(0, 3).map((_, i) => (
                      <span key={i} className="cal-day__dot" />
                    ))}
                    {eventsHere.length > 3 && (
                      <span className="cal-day__more">+{eventsHere.length - 3}</span>
                    )}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      <div className="cal-detail">
        <h3 className="cal-detail__title">
          {isLoading
            ? 'Завантажую…'
            : selectedEvents.length === 0
              ? `Подій на ${selectedDate} немає`
              : `Події на ${selectedDate}`}
        </h3>
        {selectedEvents.length > 0 && (
          <ul className="list">
            {selectedEvents.map((ev) => (
              <li key={ev.id}>
                <span>
                  <span className="list-item__title">
                    {ev.title || '(без назви)'}
                    {ev.location && (
                      <span className="list-item__inline"> · {ev.location}</span>
                    )}
                  </span>
                  <span className="list-item__sub">
                    {formatTime(ev.start) || 'Весь день'}
                  </span>
                </span>
                {ev.html_link && (
                  <a
                    href={ev.html_link}
                    target="_blank"
                    rel="noreferrer"
                    className="list-item__link"
                    aria-label="Відкрити в Google Calendar"
                  >
                    →
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
