import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import './Card.css'

interface Transaction {
  date: string
  time: string
  type: string
  amount: number | null
  currency: string
  category: string
  description: string
}

interface TransactionsResponse {
  items: Transaction[]
  spreadsheet_url: string | null
}

export function RecentTransactions() {
  const { data, isLoading, error } = useQuery<TransactionsResponse>({
    queryKey: ['transactions'],
    queryFn: () => api.get<TransactionsResponse>('/api/me/transactions?limit=10'),
    staleTime: 30_000,
  })

  return (
    <section className="card">
      <h2>💰 Останні транзакції</h2>

      {isLoading && <div className="muted">Завантажую…</div>}
      {error && <div className="muted">Не вдалось завантажити.</div>}

      {data && data.items.length === 0 && (
        <div className="empty">
          Транзакцій ще немає. Напиши боту в Telegram, наприклад:
          <br />
          <em>"Купив каву за 80 грн"</em>
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="list">
          {data.items.map((t, i) => (
            <li key={`${t.date}-${t.time}-${i}`}>
              <span>
                <strong>{t.category || '—'}</strong>
                {t.description && <span style={{ opacity: 0.7 }}> · {t.description}</span>}
                <br />
                <small style={{ opacity: 0.6 }}>{t.date} {t.time}</small>
              </span>
              <span className={t.type === 'Income' ? 'amount-pos' : 'amount-neg'}>
                {t.type === 'Income' ? '+' : '−'}
                {t.amount?.toFixed(2)} {t.currency}
              </span>
            </li>
          ))}
        </ul>
      )}

      {data?.spreadsheet_url && (
        <a className="spread-link" href={data.spreadsheet_url} target="_blank" rel="noreferrer">
          Відкрити Google Sheet →
        </a>
      )}
    </section>
  )
}
