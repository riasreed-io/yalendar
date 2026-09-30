import type { Event } from '../api'

function dayKey(event: Event): string {
  return event.start.slice(0, 10)
}

export default function WeekGrid({
  start,
  events,
  today,
}: {
  start: string
  events: Event[]
  today: string
}) {
  const byDay = new Map<string, Event[]>()
  for (const event of events) {
    const key = dayKey(event)
    const bucket = byDay.get(key)
    if (bucket) bucket.push(event)
    else byDay.set(key, [event])
  }

  const columns = Array.from({ length: 7 }, (_, offset) => {
    const day = new Date(`${start}T12:00:00`)
    day.setDate(day.getDate() + offset)
    const key = day.toISOString().slice(0, 10)
    return {
      key,
      label: day.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }),
      events: byDay.get(key) ?? [],
    }
  })

  return (
    <div className="week-grid">
      {columns.map((column) => (
        <div key={column.key} className={`week-col${column.key === today ? ' today' : ''}`}>
          <h3>{column.label}</h3>
          {column.events.length === 0 && <p className="month-more">Nothing listed</p>}
          {column.events.map((event) => (
            <div key={event.id} className="week-item">
              <span className={`cat-dot cat-${event.category}`} aria-hidden="true" />
              <div className="hit-when">
                {event.all_day
                  ? 'All day'
                  : new Date(event.start).toLocaleTimeString('en-US', {
                      hour: 'numeric',
                      minute: '2-digit',
                      timeZone: 'America/New_York',
                    })}
              </div>
              {event.url ? (
                <a href={event.url} target="_blank" rel="noopener noreferrer">
                  {event.title}
                </a>
              ) : (
                <span>{event.title}</span>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
