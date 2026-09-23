import { useState } from 'react'
import type { Event } from '../api'

function timeLabel(event: Event): string {
  if (event.all_day) return 'All day'
  const parsed = new Date(event.start)
  if (Number.isNaN(parsed.getTime())) return event.start.slice(11, 16)
  return parsed.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
  })
}

function EventRow({ event }: { event: Event }) {
  const [open, setOpen] = useState(false)
  return (
    <li className={`event ch-${event.channel}`}>
      <div className="when">{timeLabel(event)}</div>
      <div>
        <div className="event-head">
          <h3>
            {event.url ? (
              <a href={event.url} target="_blank" rel="noopener noreferrer">
                {event.title}
              </a>
            ) : (
              event.title
            )}
          </h3>
          <button
            type="button"
            className="expand-toggle"
            aria-expanded={open}
            aria-label={open ? 'Hide description' : 'Show description'}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? '▲' : '▼'}
          </button>
        </div>
        {open && (
          <p className="desc">
            {event.description || 'No description was listed for this event.'}
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
      </div>
    </li>
  )
}

export default function EventList({ events }: { events: Event[] }) {
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
