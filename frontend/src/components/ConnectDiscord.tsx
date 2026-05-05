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

export function ConnectDiscord() {
  const { user, refresh } = useAuth()
  const [code, setCode] = useState<LinkCodeResponse | null>(null)

  const discordConnected = user?.channels.some((c) => c.channel === 'discord')

  const mutation = useMutation({
    mutationFn: () =>
      api.post<LinkCodeResponse>('/api/link-codes', { channel: 'discord' }),
    onSuccess: (data) => setCode(data),
  })

  return (
    <section className="card">
      <h2>
        🎮 Discord{' '}
        {discordConnected ? (
          <span className="badge ok">підключено</span>
        ) : (
          <span className="badge muted">не підключено</span>
        )}
      </h2>

      {discordConnected ? (
        <p className="muted">
          Discord прив'язаний до твого акаунта. Пиши боту в DM або тегни
          <code> @bot </code> у каналі — він запише транзакцію або створить
          подію.
        </p>
      ) : (
        <>
          <p className="muted">
            Запроси бота на свій сервер (або відкрий DM), потім згенеруй
            одноразовий код і відправ його командою <code>/link</code>.
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
                    Запроси бота:{' '}
                    <a href={code.bot_url} target="_blank" rel="noreferrer">
                      Add to Discord
                    </a>
                  </>
                ) : (
                  'Відкрий DM з ботом у Discord'
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
