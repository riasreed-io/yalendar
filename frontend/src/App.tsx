import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchEvents, type EventsResponse } from './api'
import AskPanel from './components/AskPanel'
import Chips from './components/Chips'
import EventList from './components/EventList'
import MonthGrid from './components/MonthGrid'
import TimeSlider from './components/TimeSlider'
import WeekGrid from './components/WeekGrid'

type View = 'day' | 'week' | 'month'

function isoOf(day: Date): string {
  const month = String(day.getMonth() + 1).padStart(2, '0')
  const date = String(day.getDate()).padStart(2, '0')
  return `${day.getFullYear()}-${month}-${date}`
}

function shift(iso: string, days: number): string {
  const day = new Date(`${iso}T12:00:00`)
  day.setDate(day.getDate() + days)
  return isoOf(day)
}

function sundayOf(iso: string): string {
  const day = new Date(`${iso}T12:00:00`)
  day.setDate(day.getDate() - day.getDay())
  return isoOf(day)
}

function monthBounds(month: string): { start: string; end: string } {
  const [year, monthNumber] = month.split('-').map(Number)
  const last = new Date(year, monthNumber, 0)
  return { start: `${month}-01`, end: isoOf(last) }
}

export default function App() {
  const todayIso = useMemo(() => isoOf(new Date()), [])
  const [view, setView] = useState<View>('day')
  const [day, setDay] = useState(todayIso)
  const [month, setMonth] = useState(todayIso.slice(0, 7))

  const [channels, setChannels] = useState<string[]>([])
  const [depts, setDepts] = useState<string[]>([])
  const [cats, setCats] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [after, setAfter] = useState('all')

  const [data, setData] = useState<EventsResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const range = useMemo(() => {
    if (view === 'day') return { start: day, end: day }
    if (view === 'week') {
      const start = sundayOf(day)
      return { start, end: shift(start, 6) }
    }
    return monthBounds(month)
  }, [view, day, month])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoading(true)
      setError('')
      try {
        const result = await fetchEvents({
          ...range, channel: channels, dept: depts, cat: cats, q: query, after,
        })
        if (!cancelled) setData(result)
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Request failed')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [range, channels, depts, cats, query, after])

  const toggle = useCallback(
    (setter: React.Dispatch<React.SetStateAction<string[]>>) => (slug: string) =>
      setter((prev) => (prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug])),
    [],
  )

  const heading =
    view === 'day' ? day : view === 'week' ? `Week of ${range.start}` : month

  return (
    <>
      <header className="top">
        <div className="brand">
          <span className="yale-mark">Yale</span>
          <h1>Yalendar</h1>
          <p>Campus events for Yale students</p>
        </div>
        <nav>
          {(['day', 'week', 'month'] as View[]).map((name) => (
            <button
              key={name}
              type="button"
              className={view === name ? 'on' : ''}
              onClick={() => setView(name)}
            >
              {name[0].toUpperCase() + name.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      <main>
        <div className="layout with-chat">
          <aside className="filters">
            <label htmlFor="date-input">Date</label>
            <div className="date-nav">
              <button
                type="button"
                className="ghost"
                aria-label="Previous"
                onClick={() =>
                  view === 'month'
                    ? setMonth(shift(`${month}-01`, -1).slice(0, 7))
                    : setDay(shift(day, view === 'week' ? -7 : -1))
                }
              >
                ‹
              </button>
              <input
                id="date-input"
                type="date"
                value={day}
                onChange={(event) => {
                  setDay(event.target.value)
                  setMonth(event.target.value.slice(0, 7))
                }}
              />
              <button
                type="button"
                className="ghost"
                aria-label="Next"
                onClick={() =>
                  view === 'month'
                    ? setMonth(shift(monthBounds(month).end, 1).slice(0, 7))
                    : setDay(shift(day, view === 'week' ? 7 : 1))
                }
              >
                ›
              </button>
            </div>

            <label htmlFor="search-input">Search</label>
            <input
              id="search-input"
              type="search"
              value={query}
              placeholder="Talk, club, place…"
              onChange={(event) => setQuery(event.target.value)}
            />

            <p className="hint">
              Gold = Campus Groups (SOM), separate from Yale Connect. Listings cover about
              a month of public Yale, Connect, Campus Groups and New Haven events.
            </p>
          </aside>

          <section className="feed">
            <div className="meta-row">
              <div>
                <h2>{heading}</h2>
                <p>
                  {loading
                    ? 'Loading…'
                    : data
                      ? `${data.count} of ${data.total} event${data.total === 1 ? '' : 's'}`
                      : ''}
                </p>
              </div>
              <button type="button" className="ghost" onClick={() => setDay(todayIso)}>
                Jump to today
              </button>
            </div>

            {error && <p className="error">Could not reach the calendar: {error}</p>}

            <TimeSlider value={after} onChange={setAfter} />

            {data && (
              <>
                <Chips
                  label="Source"
                  options={data.facets.channels}
                  selected={channels}
                  onToggle={toggle(setChannels)}
                  onClear={() => setChannels([])}
                  colorBySlug
                />
                <Chips
                  label="School / department"
                  options={data.facets.departments}
                  selected={depts}
                  onToggle={toggle(setDepts)}
                  onClear={() => setDepts([])}
                />
                <Chips
                  label="Topic"
                  options={data.facets.categories}
                  selected={cats}
                  onToggle={toggle(setCats)}
                  onClear={() => setCats([])}
                />
              </>
            )}

            {data && view === 'day' && <EventList events={data.events} />}
            {data && view === 'week' && (
              <WeekGrid start={range.start} events={data.events} today={data.today} />
            )}
            {data && view === 'month' && (
              <MonthGrid month={month} events={data.events} today={data.today} />
            )}
          </section>

          <AskPanel />
        </div>
      </main>
    </>
  )
}
