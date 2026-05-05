import { CalendarMonthGrid } from '../components/CalendarMonthGrid'
import { UpcomingEvents } from '../components/UpcomingEvents'

export function CalendarPage() {
  return (
    <>
      <section className="page-hero">
        <div>
          <p className="page-hero__eyebrow">Розклад</p>
          <h1 className="page-hero__title">Календар 📅</h1>
          <p className="page-hero__lead">
            Місячна сітка з твого Google Calendar — клацай по дню щоб
            побачити події. Створення — через бота: «Зустріч завтра о 14:00».
          </p>
        </div>
      </section>

      <div className="page-grid">
        <div className="page-grid__col">
          <CalendarMonthGrid />
        </div>
        <div className="page-grid__col">
          <UpcomingEvents />
        </div>
      </div>
    </>
  )
}
