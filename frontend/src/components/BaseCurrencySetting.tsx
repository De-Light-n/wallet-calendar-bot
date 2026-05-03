import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import './Card.css'

interface BaseCurrencyResponse {
  base_currency: string
  supported: string[]
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
      api.put<{ base_currency: string }>('/api/me/base-currency', {
        currency: code,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['auth', 'me'] })
      qc.invalidateQueries({ queryKey: ['me', 'base-currency'] })
      qc.invalidateQueries({ queryKey: ['finance'] })
      setPendingCode(null)
    },
  })

  return (
    <section className="card">
      <h2>💱 Базова валюта</h2>
      <p className="card-subtitle">
        У ній рахуються підсумки в дашборді. Транзакції в інших валютах
        конвертуються через офіційний курс НБУ і фіксуються на дату запису.
      </p>

      <div className="tz-row">
        <select
          value={selected}
          onChange={(e) => setPendingCode(e.target.value)}
          className="tz-select"
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
          {mutation.isPending ? 'Зберігаю…' : 'Зберегти'}
        </button>
      </div>

      <div className="tz-status" aria-live="polite">
        {mutation.isError && (
          <span className="muted small tz-status--err">Помилка збереження</span>
        )}
        {mutation.isSuccess && (
          <span className="muted small tz-status--ok">
            Збережено ✓ Старі транзакції залишаться в попередній валюті — натисни
            "Перестворити Sheet" щоб таблиця теж переключилась.
          </span>
        )}
      </div>
    </section>
  )
}
