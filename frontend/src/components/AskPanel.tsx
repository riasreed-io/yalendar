import { useEffect, useRef, useState } from 'react'
import { ask, fetchAgentStatus, type AgentStatus, type AskResponse } from '../api'

const EXAMPLES = [
  'free food this week',
  "what's happening tonight",
  'talks tomorrow',
  'concerts this weekend',
]

type Turn =
  | { kind: 'me'; text: string }
  | { kind: 'bot'; pending: true }
  | { kind: 'bot'; pending: false; data: AskResponse }

export default function AskPanel() {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchAgentStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    document.body.classList.toggle('chat-open', open)
  }, [open])

  useEffect(() => {
    const node = scroller.current
    if (node) node.scrollTop = node.scrollHeight
  }, [turns])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  // Use the model only when the backend says it is both allowed and keyed;
  // otherwise go straight to the free local search.
  const useAgent = Boolean(status?.allowed && status?.configured)

  async function send(question: string) {
    const text = question.trim()
    if (!text) return
    setDraft('')
    setTurns((prev) => [...prev, { kind: 'me', text }, { kind: 'bot', pending: true }])
    try {
      const data = await ask(text, useAgent)
      setTurns((prev) => [...prev.slice(0, -1), { kind: 'bot', pending: false, data }])
    } catch {
      setTurns((prev) => [
        ...prev.slice(0, -1),
        {
          kind: 'bot',
          pending: false,
          data: {
            reply: 'Something went wrong reaching the calendar. Try again in a moment.',
            events: [], more: 0, link: '', link_label: '', suggestions: [], engine: 'local',
          },
        },
      ])
    }
  }

  return (
    <>
      <aside
        className={`chat-dock${open ? ' open' : ''}`}
        id="chat-dock"
        aria-label="Ask Yalendar"
      >
        <div className="chat-dock-head">
          <h2>Ask Yalendar</h2>
          <button
            type="button"
            className="chat-close"
            aria-label="Close the assistant"
            onClick={() => setOpen(false)}
          >
            ×
          </button>
        </div>

        <div className="chat" ref={scroller}>
          <div className="bubble bot">
            <p>Looking for something? Ask me and I&rsquo;ll search the listings.</p>
          </div>
          {turns.map((turn, index) =>
            turn.kind === 'me' ? (
              <div className="bubble me" key={index}>
                <p>{turn.text}</p>
              </div>
            ) : turn.pending ? (
              <div className="bubble bot" key={index}>
                <span className="dots">
                  <span />
                  <span />
                </span>
              </div>
            ) : (
              <div className="bubble bot" key={index}>
                <p>{turn.data.reply}</p>
                {turn.data.events.length > 0 && (
                  <ul className="hits">
                    {turn.data.events.map((hit, i) => (
                      <li key={i}>
                        <span className={`dot ${hit.channel}`} aria-hidden="true" />
                        <div>
                          <p className="hit-when">{hit.when}</p>
                          {hit.url ? (
                            <a className="hit-title" href={hit.url} target="_blank" rel="noopener noreferrer">
                              {hit.title}
                            </a>
                          ) : (
                            <span className="hit-title">{hit.title}</span>
                          )}
                          <p className="hit-meta">
                            {[hit.org, hit.location].filter(Boolean).join(' · ')}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                {turn.data.more > 0 && <p className="hit-more">and {turn.data.more} more</p>}
                {turn.data.note && <p className="hit-more">{turn.data.note}</p>}
                <p className="engine-tag">
                  {turn.data.engine === 'agent' ? 'AI assistant' : 'Free search'}
                  {turn.data.tools_used?.length ? ` · ${turn.data.tools_used.join(', ')}` : ''}
                </p>
              </div>
            ),
          )}
        </div>

        <div className="ask-examples">
          {EXAMPLES.map((idea) => (
            <button type="button" className="chip" key={idea} onClick={() => send(idea)}>
              {idea}
            </button>
          ))}
        </div>

        <form
          className="ask-form"
          onSubmit={(event) => {
            event.preventDefault()
            send(draft)
          }}
        >
          <input
            type="text"
            value={draft}
            maxLength={300}
            placeholder="e.g. free food tomorrow"
            aria-label="Ask about upcoming events"
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit">Ask</button>
        </form>
      </aside>

      <button
        type="button"
        className="chat-launch"
        aria-expanded={open}
        aria-controls="chat-dock"
        onClick={() => setOpen((v) => !v)}
      >
        💬 Ask
      </button>
    </>
  )
}
