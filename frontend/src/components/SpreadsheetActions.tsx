import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import './Card.css'
import './SpreadsheetActions.css'

interface ResetResponse {
  status: 'ok'
  spreadsheet_id: string
  spreadsheet_url: string
  old_spreadsheet_id: string | null
  schema_version: number
}

export function SpreadsheetActions() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [last, setLast] = useState<ResetResponse | null>(null)

  const mutation = useMutation({
    mutationFn: () => api.post<ResetResponse>('/api/me/spreadsheet/reset'),
    onSuccess: (data) => {
      setLast(data)
      setConfirming(false)
      qc.invalidateQueries({ queryKey: ['auth', 'me'] })
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['finance'] })
    },
    onError: () => setConfirming(false),
  })

  const hasSheet = !!user?.google_spreadsheet_id
  const sheetUrl = user?.google_spreadsheet_id
    ? `https://docs.google.com/spreadsheets/d/${user.google_spreadsheet_id}/edit`
    : null

  return (
    <section className="card">
      <h2>📊 Google-таблиця</h2>
      <p className="card-subtitle">
        Куди записуються транзакції та де живуть формули дашборду й графіків.
      </p>

      {hasSheet && sheetUrl && (
        <a
          className="ghost-btn sheet-open-btn"
          href={sheetUrl}
          target="_blank"
          rel="noreferrer"
        >
          Відкрити поточну
        </a>
      )}

      {!confirming && !mutation.isPending && (
        <button
          className="primary-btn sheet-reset-btn"
          onClick={() => setConfirming(true)}
        >
          {hasSheet ? 'Перестворити таблицю' : 'Створити таблицю'}
        </button>
      )}

      {confirming && (
        <div className="sheet-confirm">
          <p className="muted">
            {hasSheet
              ? 'Створиться нова таблиця з останнім layout. Стара залишиться у твоєму Google Drive — її можна видалити вручну.'
              : 'Буде створено нову Google-таблицю на твоєму акаунті.'}
          </p>
          <div className="sheet-confirm__row">
            <button
              className="primary-btn"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
            >
              Так, створити
            </button>
            <button
              className="ghost-btn"
              onClick={() => setConfirming(false)}
              disabled={mutation.isPending}
            >
              Скасувати
            </button>
          </div>
        </div>
      )}

      {mutation.isPending && (
        <div className="muted small sheet-status">
          Створюю таблицю та малюю формули…
        </div>
      )}

      {mutation.isError && (
        <div className="muted small tz-status--err">
          Не вдалося. Перевір що Google авторизований і має права на Sheets.
        </div>
      )}

      {last && !mutation.isPending && (
        <div className="muted small tz-status--ok sheet-status">
          ✓ Готово.{' '}
          <a href={last.spreadsheet_url} target="_blank" rel="noreferrer">
            Відкрити нову
          </a>
          {last.old_spreadsheet_id && (
            <>
              {' · '}Стара (<code>{last.old_spreadsheet_id.slice(0, 8)}…</code>)
              лишилась у Drive.
            </>
          )}
        </div>
      )}
    </section>
  )
}
