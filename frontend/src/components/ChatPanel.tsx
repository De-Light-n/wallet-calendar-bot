import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import './ChatPanel.css'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

const SUGGESTIONS = [
  'Витратив 150 на каву',
  'Зустріч з Сашею завтра о 14:00',
  'Що в мене на цьому тижні?',
  'Купив пиво за 50 грн',
] as const

function nextId(): string {
  return Math.random().toString(36).slice(2)
}

export function ChatPanel() {
  const qc = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)

  const mutation = useMutation({
    mutationFn: (text: string) =>
      api.post<{ response: string }>('/api/me/chat', { text }),
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: 'assistant', content: data.response },
      ])
      // Anything the agent did (record_transaction, calendar event, /currency)
      // may have updated server-side data — refresh widgets across the app.
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['calendar'] })
      qc.invalidateQueries({ queryKey: ['finance'] })
      qc.invalidateQueries({ queryKey: ['auth', 'me'] })
    },
    onError: (err) => {
      const message =
        err instanceof Error ? err.message : 'Сталася помилка'
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: 'assistant',
          content: `❌ ${message}`,
        },
      ])
    },
  })

  // Auto-scroll to the bottom on each message change so the latest reply is
  // visible without manual scroll. Lives in an effect so the DOM is updated
  // before we measure scrollHeight.
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages, mutation.isPending])

  function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || mutation.isPending) return
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: 'user', content: trimmed },
    ])
    setDraft('')
    mutation.mutate(trimmed)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    send(draft)
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter inserts a newline — chat-app convention.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(draft)
    }
  }

  const empty = messages.length === 0 && !mutation.isPending

  return (
    <section className="chat-card">
      <div className="chat-card__head">
        <div>
          <p className="chat-card__eyebrow">Чат з ботом</p>
          <h2 className="chat-card__title">Що записати або запланувати?</h2>
        </div>
      </div>

      <div className="chat-list" ref={listRef} aria-live="polite">
        {empty && (
          <div className="chat-empty">
            <p>
              Пиши природною мовою — я запишу транзакцію, створю подію в
              Google Calendar або відповім на питання про твій графік чи
              бюджет.
            </p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat-suggestion"
                  onClick={() => send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`chat-msg chat-msg--${m.role}`}>
            <div className="chat-bubble">{m.content}</div>
          </div>
        ))}

        {mutation.isPending && (
          <div className="chat-msg chat-msg--assistant">
            <div className="chat-bubble chat-bubble--typing">
              <span className="chat-dot" />
              <span className="chat-dot" />
              <span className="chat-dot" />
            </div>
          </div>
        )}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        <textarea
          ref={inputRef}
          className="chat-input"
          placeholder="Напиши що-небудь… (Enter — надіслати, Shift+Enter — новий рядок)"
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={mutation.isPending}
        />
        <button
          type="submit"
          className="chat-send"
          disabled={!draft.trim() || mutation.isPending}
          aria-label="Надіслати"
        >
          {mutation.isPending ? '…' : 'Надіслати'}
        </button>
      </form>
    </section>
  )
}
