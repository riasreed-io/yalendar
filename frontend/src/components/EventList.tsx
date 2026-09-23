import { memo, useState } from 'react'
import { fetchEventDetail, type Event } from '../api'

function timeLabel(event: Event): string {
  if (event.all_day) return 'All day'
  const parsed = new Date(event.start)
  if (Number.isNaN(parsed.getTime())) return event.start.slice(11, 16)
  return parsed.toLocaleTimeString('en-US', {
    hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York',
  })
}

const EventRow = memo(function EventRow({ event }: { event: Event }) {
  const [open, setOpen] = useState(false)
  const [description, setDescription] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Descriptions are not in the list payload; pull this one on first open.
  async function toggle() {
    const next = !open
    setOpen(next)
    if (next && description === null && event.has_description) {
      setLoading(true)
      try {
        const detail = await fetchEventDetail(event.id)
        setDescription(detail.description)
      } catch {
        setDescription('Could not load the description.')
      } finally {
        setLoading(false)
      }
    }
  }

  return (
    <li className={`event ch-${event.channel}`}>
      <div className="when">{timeLabel(event)}</div>
      <div>
        <div className="event-head">
          <h3>
            {event.url ? (
              <a href={event.url} target="_blank" rel="noopener noreferrer">{event.title}</a>
            ) : (
              event.title
            )}
          </h3>
          <button
            type="button"
            className="expand-toggle"
            aria-expanded={open}
            aria-label={open ? 'Hide description' : 'Show description'}
            onClick={toggle}
          >
            {open ? '▲' : '▼'}
          </button>
        </div>
        {open && (
          <p className="desc">
            {loading
              ? 'Loading…'
              : event.has_description
                ? (description ?? '')
                : 'No description was listed for this event.'}
          </p>
        )}
        <p className="pills">
          <span className={`pill ch-${event.channel}`}>{event.channel_label}</span>
          <span className="pill">{event.dept_label}</span>
          <span className="pill">{event.category_label}</span>
        </p>
        <p className="sub">
          {event.org}
          {event.location ? ` · ${event.location}` : ''}
        </p>
        {event.also_listed.length > 0 && (
          <p className="sub">Also on {event.also_listed.join(', ')}</p>
        )}
      </div>
    </li>
  )
})

function EventList({ events }: { events: Event[] }) {
  if (events.length === 0) {
    return <p className="empty">No events match these filters. Try clearing one.</p>
  }
  return (
    <ol className="events">
      {events.map((event) => (
        <EventRow key={event.id} event={event} />
      ))}
    </ol>
  )
}

export default memo(EventList)
