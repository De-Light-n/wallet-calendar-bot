import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import './Card.css'
import './FinanceSummary.css'

interface CategoryRow {
  category: string
  type: 'Expense' | 'Income'
  amount: number
  count: number
}

interface MonthRow {
  month: string // "YYYY-MM"
  expense: number
  income: number
  balance: number
}

interface SummaryResponse {
  by_category: CategoryRow[]
  by_month: MonthRow[]
  totals: {
    expense: number
    income: number
    balance: number
    count: number
  }
}

// Tailwind-ish palette tuned to look distinct on both light & dark themes.
const PIE_COLORS = [
  '#ef4444',
  '#f97316',
  '#f59e0b',
  '#eab308',
  '#84cc16',
  '#22c55e',
  '#10b981',
  '#06b6d4',
  '#3b82f6',
  '#8b5cf6',
  '#d946ef',
  '#ec4899',
]

function formatMoney(n: number): string {
  return n.toLocaleString('uk-UA', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

// "2026-05" → "тра 26" (short month + 2-digit year)
const MONTH_LABELS_UK = [
  'січ', 'лют', 'бер', 'кві', 'тра', 'чер',
  'лип', 'сер', 'вер', 'жов', 'лис', 'гру',
]
function formatMonthLabel(ym: string): string {
  const [y, m] = ym.split('-')
  const mi = parseInt(m, 10) - 1
  if (mi < 0 || mi > 11) return ym
  return `${MONTH_LABELS_UK[mi]} ${y.slice(2)}`
}

export function FinanceSummary() {
  const { data, isLoading, error } = useQuery<SummaryResponse>({
    queryKey: ['finance', 'summary'],
    queryFn: () => api.get<SummaryResponse>('/api/me/finance/summary?months=12'),
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <section className="card">
        <h2>📊 Зведення</h2>
        <p className="muted">Завантажую…</p>
      </section>
    )
  }

  if (error || !data) {
    return (
      <section className="card">
        <h2>📊 Зведення</h2>
        <p className="muted">Не вдалось завантажити дані.</p>
      </section>
    )
  }

  const expenseCategories = data.by_category.filter((c) => c.type === 'Expense')
  const hasMonthly = data.by_month.some((m) => m.expense > 0 || m.income > 0)
  const hasCategories = expenseCategories.length > 0
  const monthlyData = data.by_month.map((m) => ({
    ...m,
    label: formatMonthLabel(m.month),
  }))

  return (
    <>
      <section className="kpi-grid">
        <article className="kpi-card kpi-card--expense">
          <div className="kpi-card__label">Витрати (за весь час)</div>
          <div className="kpi-card__value">{formatMoney(data.totals.expense)}</div>
        </article>
        <article className="kpi-card kpi-card--income">
          <div className="kpi-card__label">Доходи</div>
          <div className="kpi-card__value">{formatMoney(data.totals.income)}</div>
        </article>
        <article
          className={`kpi-card ${
            data.totals.balance >= 0 ? 'kpi-card--income' : 'kpi-card--expense'
          }`}
        >
          <div className="kpi-card__label">Баланс</div>
          <div className="kpi-card__value">
            {data.totals.balance >= 0 ? '+' : ''}
            {formatMoney(data.totals.balance)}
          </div>
        </article>
        <article className="kpi-card">
          <div className="kpi-card__label">Транзакцій</div>
          <div className="kpi-card__value">{data.totals.count}</div>
        </article>
      </section>

      <section className="card chart-card">
        <h2>📈 Витрати vs Доходи (12 міс.)</h2>
        <p className="card-subtitle">
          Помісячний розріз. Місяці без транзакцій залишаються пустими.
        </p>
        {hasMonthly ? (
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={monthlyData}
                margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  stroke="var(--text-muted)"
                  tick={{ fontSize: 12 }}
                />
                <YAxis
                  stroke="var(--text-muted)"
                  tick={{ fontSize: 12 }}
                  width={60}
                />
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    color: 'var(--text-h)',
                  }}
                  formatter={(v) =>
                    typeof v === 'number' ? formatMoney(v) : String(v)
                  }
                />
                <Legend wrapperStyle={{ fontSize: 13, paddingTop: 8 }} />
                <Bar dataKey="expense" name="Витрати" fill="#ef4444" radius={[4, 4, 0, 0]} />
                <Bar dataKey="income" name="Доходи" fill="#22c55e" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="empty">Поки немає даних для побудови графіка.</div>
        )}
      </section>

      <section className="card chart-card">
        <h2>🥧 Витрати по категоріях</h2>
        <p className="card-subtitle">За весь час (тільки expense-категорії)</p>
        {hasCategories ? (
          <div className="chart-wrap chart-wrap--pie">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={expenseCategories}
                  dataKey="amount"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  outerRadius={110}
                  label={({ name, percent }) =>
                    `${name}: ${((percent ?? 0) * 100).toFixed(0)}%`
                  }
                  labelLine={false}
                >
                  {expenseCategories.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    color: 'var(--text-h)',
                  }}
                  formatter={(v) =>
                    typeof v === 'number' ? formatMoney(v) : String(v)
                  }
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="empty">Поки немає витрат по категоріях.</div>
        )}
      </section>
    </>
  )
}
