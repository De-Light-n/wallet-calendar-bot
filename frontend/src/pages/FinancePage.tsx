import { useAuth } from '../auth/AuthContext'
import { FinanceSummary } from '../components/FinanceSummary'
import { RecentTransactions } from '../components/RecentTransactions'

export function FinancePage() {
  const { user } = useAuth()

  return (
    <>
      <section className="page-hero">
        <div>
          <p className="page-hero__eyebrow">Фінанси</p>
          <h1 className="page-hero__title">Кошти 💰</h1>
          <p className="page-hero__lead">
            Зведення витрат і доходів по категоріях і місяцях. Деталі — у
            таблиці нижче або у Google Sheet.
          </p>
        </div>
        {user?.google_spreadsheet_id && (
          <a
            className="page-hero__cta"
            href={`https://docs.google.com/spreadsheets/d/${user.google_spreadsheet_id}/edit`}
            target="_blank"
            rel="noreferrer"
          >
            <span aria-hidden="true">📊</span>
            <span>Відкрити Google Sheet</span>
          </a>
        )}
      </section>

      <div className="page-stack">
        <FinanceSummary />
        <RecentTransactions />
      </div>
    </>
  )
}
