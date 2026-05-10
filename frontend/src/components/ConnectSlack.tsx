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

export function ConnectSlack() {
  const { user, refresh } = useAuth()
  const [code, setCode] = useState<LinkCodeResponse | null>(null)

  const slackConnected = user?.channels.some((c) => c.channel === 'slack')

  const mutation = useMutation({
    mutationFn: () =>
      api.post<LinkCodeResponse>('/api/link-codes', { channel: 'slack' }),
    onSuccess: (data) => setCode(data),
  })

  return (
    <section className="card">
      <h2>
        💼 Slack{' '}
        {slackConnected ? (
          <span className="badge ok">підключено</span>
        ) : (
          <span className="badge muted">не підключено</span>
        )}
      </h2>

      {slackConnected ? (
        <p className="muted">
          Slack прив'язаний до твого акаунта. Пиши боту в DM або тегни
          <code> @bot </code> в каналі — він запише транзакцію або створить
          подію.
        </p>
      ) : (
        <>
          <ol className="howto">
            <li>Установи бот у свій Slack workspace.</li>
            <li>
              Знайди бота у Slack: <em>головне меню → Apps → пошук</em>.
            </li>
            <li>
              Відкрий DM з ботом (або згадай його <code>@bot</code> у каналі) і
              надішли команду <code>/link &lt;код&gt;</code>.
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
                      Установи бот у свій workspace:{' '}
                      <a href={code.bot_url} target="_blank" rel="noreferrer">
                        Add to Slack
                      </a>
                      .
                    </>
                  ) : (
                    <>
                      Попроси адміна workspace додати бот{' '}
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
                  У Slack відкрий <em>Apps</em> →{' '}
                  {code.bot_name ? (
                    <>
                      знайди <strong>{code.bot_name}</strong>
                    </>
                  ) : (
                    'знайди бота за ім\'ям, яке вказав адмін'
                  )}{' '}
                  → відкрий DM.
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
