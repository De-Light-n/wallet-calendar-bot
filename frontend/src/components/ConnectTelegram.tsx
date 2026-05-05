import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import './Card.css'

interface LinkCodeResponse {
  code: string
  expires_at: string
  channel: string
  bot_url: string | null
  instructions: string
}

export function ConnectTelegram() {
  const { user, refresh } = useAuth()
  const [code, setCode] = useState<LinkCodeResponse | null>(null)

  const tgConnected = user?.channels.some((c) => c.channel === 'telegram')

  const mutation = useMutation({
    mutationFn: () =>
      api.post<LinkCodeResponse>('/api/link-codes', { channel: 'telegram' }),
    onSuccess: (data) => setCode(data),
  })

  return (
    <section className="card">
      <h2>
        💬 Telegram{' '}
        {tgConnected ? (
          <span className="badge ok">підключено</span>
        ) : (
          <span className="badge muted">не підключено</span>
        )}
      </h2>

      {tgConnected ? (
        <p className="muted">
          Бот прив'язаний до твого акаунта. Просто пиши йому — він запише
          транзакцію або створить подію.
        </p>
      ) : (
        <>
          <p className="muted">
            Щоб підключити Telegram, згенеруй одноразовий код і введи його в боті
            командою <code>/link</code>.
          </p>

          {!code && (
            <button
              className="primary-btn"
              disabled={mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? 'Генерую…' : 'Згенерувати код'}
            </button>
          )}

          {code && (
            <div className="code-block">
              <div className="code-value">{code.code}</div>
              <p className="muted">
                {code.bot_url ? (
                  <>
                    Відкрий бота:{' '}
                    <a href={code.bot_url} target="_blank" rel="noreferrer">
                      {code.bot_url}
                    </a>
                  </>
                ) : (
                  'Відкрий свого Telegram-бота'
                )}{' '}
                і напиши:
              </p>
              <pre className="cmd">/link {code.code}</pre>
              <p className="muted small">
                Код діє 10 хвилин. Після прив'язки оновіть сторінку.
              </p>
              <button
                className="ghost-btn"
                onClick={() => {
                  setCode(null)
                  refresh()
                }}
              >
                Готово
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
