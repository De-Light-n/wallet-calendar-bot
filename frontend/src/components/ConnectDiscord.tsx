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
  bot_name: string | null
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
          <ol className="howto">
            <li>
              Запроси бот на свій Discord-сервер (потрібні права на читання й
              надсилання повідомлень).
            </li>
            <li>
              Відкрий DM з ботом або канал, де він присутній — згадай його як{' '}
              <code>@bot</code>, щоб він почув повідомлення.
            </li>
            <li>
              Надішли команду <code>/link &lt;код&gt;</code>.
            </li>
          </ol>

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

              <ol className="howto">
                <li>
                  {code.bot_url ? (
                    <>
                      Запроси бот на сервер:{' '}
                      <a href={code.bot_url} target="_blank" rel="noreferrer">
                        Add to Discord
                      </a>
                      .
                    </>
                  ) : (
                    <>
                      Попроси адміна сервера додати бот{' '}
                      {code.bot_name ? (
                        <strong>{code.bot_name}</strong>
                      ) : (
                        'Wallet Calendar'
                      )}
                      .
                    </>
                  )}
                </li>
                <li>
                  Відкрий DM з ботом{' '}
                  {code.bot_name ? (
                    <>
                      (<strong>{code.bot_name}</strong>)
                    </>
                  ) : null}{' '}
                  або згадай його у каналі через <code>@bot</code>.
                </li>
                <li>Надішли команду:</li>
              </ol>

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
