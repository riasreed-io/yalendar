import type { Event } from '../api'

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const PER_CELL = 4

function isoOf(day: Date): string {
  // Local date, not UTC: toISOString would shift the day in New York.
  const month = String(day.getMonth() + 1).padStart(2, '0')
  const date = String(day.getDate()).padStart(2, '0')
  return `${day.getFullYear()}-${month}-${date}`
}

export default function MonthGrid({
  month,
  events,
  today,
}: {
  month: string // YYYY-MM
  events: Event[]
  today: string
}) {
  const byDay = new Map<string, Event[]>()
  for (const event of events) {
    const key = event.start.slice(0, 10)
    const bucket = byDay.get(key)
    if (bucket) bucket.push(event)
    else byDay.set(key, [event])
  }

  const [year, monthNumber] = month.split('-').map(Number)
  const first = new Date(year, monthNumber - 1, 1)
  const gridStart = new Date(first)
  gridStart.setDate(1 - first.getDay())

  const weeks: Date[][] = []
  const cursor = new Date(gridStart)
  for (let w = 0; w < 6; w += 1) {
    const week: Date[] = []
    for (let d = 0; d < 7; d += 1) {
      week.push(new Date(cursor))
      cursor.setDate(cursor.getDate() + 1)
    }
    weeks.push(week)
    if (cursor.getMonth() !== monthNumber - 1 && cursor.getDate() > 7) break
  }

  return (
    <div>
      <div className="month-weekdays">
        {WEEKDAYS.map((name) => (
          <div key={name}>{name}</div>
        ))}
      </div>
      {weeks.map((week) => (
        <div className="month-week" key={isoOf(week[0])}>
          {week.map((day) => {
            const key = isoOf(day)
            const items = byDay.get(key) ?? []
            const inMonth = day.getMonth() === monthNumber - 1
            return (
              <div
                key={key}
                className={`month-cell${inMonth ? '' : ' out'}${key === today ? ' today' : ''}`}
              >
                <div className="month-num">{day.getDate()}</div>
                <ul>
                  {items.slice(0, PER_CELL).map((event) => (
                    <li key={event.id}>
                      {event.url ? (
                        <a href={event.url} target="_blank" rel="noopener noreferrer">
                          {event.title}
                        </a>
                      ) : (
                        event.title
                      )}
                    </li>
                  ))}
                </ul>
                {items.length > PER_CELL && (
                  <div className="month-more">+{items.length - PER_CELL} more</div>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
