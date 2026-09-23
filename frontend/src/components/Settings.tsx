import { useEffect, useState } from 'react'
import { fetchFeeds, saveFeeds } from '../api'

/** Extra ICS feeds folded into ingest, matching the server-rendered page. */
export default function Settings() {
  const [text, setText] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchFeeds()
      .then((data) => setText(data.urls.join('\n')))
      .catch((err: unknown) => setStatus(err instanceof Error ? err.message : 'Load failed'))
  }, [])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setStatus('')
    try {
      const urls = text.split('\n').map((line) => line.trim()).filter(Boolean)
      const saved = await saveFeeds(urls)
      setStatus(`Saved ${saved.saved} feed${saved.saved === 1 ? '' : 's'}.`)
    } catch (err: unknown) {
      setStatus(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Extra calendar feeds</h2>
      <p className="hint">
        One ICS URL per line. These are pulled alongside the built-in sources on
        the next refresh.
      </p>
      <form onSubmit={submit}>
        <textarea
          rows={8}
          value={text}
          spellCheck={false}
          placeholder="https://example.edu/events.ics"
          onChange={(event) => setText(event.target.value)}
        />
        <div className="row">
          <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save feeds'}</button>
          {status && <span className="hint">{status}</span>}
        </div>
      </form>
    </section>
  )
}
