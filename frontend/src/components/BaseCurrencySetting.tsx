import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import './Card.css'

interface BaseCurrencyResponse {
  base_currency: string
  supported: string[]
}

interface RecalcSummary {
  status: string
  updated: number
  skipped: number
  fx_failures: number
  base_currency?: string
}

interface UpdateBaseCurrencyResponse {
  base_currency: string
  previous: string
  recalculation: RecalcSummary | null
}

export function BaseCurrencySetting() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [pendingCode, setPendingCode] = useState<string | null>(null)

  // Pull supported list from the server so it stays in sync with FX whitelist
  // without hardcoding the same list on the frontend.
  const { data } = useQuery<BaseCurrencyResponse>({
    queryKey: ['me', 'base-currency'],
    queryFn: () => api.get<BaseCurrencyResponse>('/api/me/base-currency'),
    staleTime: 60_000,
  })

  const current = user?.base_currency ?? 'UAH'
  const selected = pendingCode ?? current
  const supported = data?.supported ?? [current]

  const mutation = useMutation({
    mutationFn: (code: string) =>
      api.put<UpdateBaseCurrencyResponse>('/api/me/base-currency', {
        currency: code,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth', 'me'] })
      qc.invalidateQueries({ queryKey: ['me', 'base-currency'] })
      qc.invalidateQueries({ queryKey: ['finance'] })
      qc.invalidateQueries({ queryKey: ['transactions'] })
      setPendingCode(null)
    },
  })

  return (
    <section className="card">
      <h2>💱 Базова валюта</h2>
      <p className="card-subtitle">
        У ній рахуються підсумки в дашборді. При зміні бот перерахує всі
        існуючі транзакції за курсом НБУ на дату кожного запису.
      </p>

      <div className="tz-row">
        <select
          value={selected}
          onChange={(e) => setPendingCode(e.target.value)}
          className="tz-select"
          disabled={mutation.isPending}
        >
          {supported.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        <button
          className="primary-btn"
          disabled={mutation.isPending || selected === current}
          onClick={() => mutation.mutate(selected)}
        >
          {mutation.isPending ? 'Перераховую…' : 'Зберегти'}
        </button>
      </div>

      <div className="tz-status" aria-live="polite">
        {mutation.isError && (
          <span className="muted small tz-status--err">Помилка збереження</span>
        )}
        {mutation.isSuccess && (() => {
          const recalc = mutation.data?.recalculation
          if (!recalc || recalc.status === 'skipped') {
            return (
              <span className="muted small tz-status--ok">
                Збережено ✓ (старий формат таблиці — рядки не перераховувались)
              </span>
            )
          }
          if (recalc.status !== 'ok') {
            return (
              <span className="muted small tz-status--err">
                Збережено, але перерахунок не вдався. Спробуй пізніше.
              </span>
            )
          }
          const parts = [`Перераховано ${recalc.updated} транзакцій`]
          if (recalc.skipped > 0) parts.push(`пропущено ${recalc.skipped}`)
          if (recalc.fx_failures > 0)
            parts.push(`без курсу: ${recalc.fx_failures}`)
          return (
            <span className="muted small tz-status--ok">
              Збережено ✓ {parts.join(' · ')}
            </span>
          )
        })()}
      </div>
    </section>
  )
}
