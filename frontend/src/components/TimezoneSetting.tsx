import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import './Card.css'

// Common Ukrainian/EU timezones; user can paste any IANA name in custom field if needed.
const COMMON_ZONES = [
  'UTC',
  'Europe/Kyiv',
  'Europe/Warsaw',
  'Europe/Berlin',
  'Europe/London',
  'America/New_York',
  'America/Los_Angeles',
  'Asia/Tokyo',
]

export function TimezoneSetting() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [tz, setTz] = useState(user?.timezone ?? 'UTC')

  const mutation = useMutation({
    mutationFn: (newTz: string) => api.put<{ timezone: string }>('/api/me/timezone', { timezone: newTz }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['auth', 'me'] }),
  })

  const options = COMMON_ZONES.includes(tz) ? COMMON_ZONES : [tz, ...COMMON_ZONES]

  return (
    <section className="card">
      <h2>⚙️ Часовий пояс</h2>
      <p className="muted">Використовується для обробки часу в подіях календаря.</p>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <select
          value={tz}
          onChange={(e) => setTz(e.target.value)}
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'var(--bg)',
            color: 'var(--text-h)',
            fontSize: 14,
          }}
        >
          {options.map((z) => (
            <option key={z} value={z}>{z}</option>
          ))}
        </select>
        <button
          className="primary-btn"
          disabled={mutation.isPending || tz === user?.timezone}
          onClick={() => mutation.mutate(tz)}
        >
          {mutation.isPending ? 'Зберігаю…' : 'Зберегти'}
        </button>
        {mutation.isError && <span className="muted small" style={{ color: '#dc2626' }}>Помилка</span>}
        {mutation.isSuccess && <span className="muted small" style={{ color: '#16a34a' }}>Збережено ✓</span>}
      </div>
    </section>
  )
}
