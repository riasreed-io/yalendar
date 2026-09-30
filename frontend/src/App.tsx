import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  fetchEvents,
  fetchRefreshStatus,
  startRefresh,
  type EventsResponse,
} from './api'
import AskPanel from './components/AskPanel'
import Chips from './components/Chips'
import EventList from './components/EventList'
import MiniMonth from './components/MiniMonth'
import MonthGrid from './components/MonthGrid'
import Settings from './components/Settings'
import TimeSlider from './components/TimeSlider'
import WeekGrid from './components/WeekGrid'
import { todayIso, useUrlState, type View } from './urlState'

const SORTS: [string, string][] = [
  ['time', 'Time'], ['org', 'Organization'], ['dept', 'Department'], ['title', 'Title'],
]
const GROUPS: [string, string][] = [
  ['none', 'One list'], ['channel', 'Source'], ['category', 'Category'],
  ['dept', 'Department'], ['org', 'Organization'],
]
const NAV: View[] = ['day', 'week', 'month', 'settings']
const SEARCH_DEBOUNCE_MS = 250

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

function monthEnd(month: string): string {
  const [year, monthNumber] = month.split('-').map(Number)
  return isoOf(new Date(year, monthNumber, 0))
}

export default function App() {
  const { state, patch, toggleIn } = useUrlState()
  const [data, setData] = useState<EventsResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState('')
  // On a phone the sidebar collapses to a one-line control so chips and
  // events stay at the top of the page, matching the server-rendered site.
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  // Typing in the search box should not fire a request per keystroke.
  const [draftQuery, setDraftQuery] = useState(state.q)
  const [seenQuery, setSeenQuery] = useState(state.q)
  if (state.q !== seenQuery) {
    setSeenQuery(state.q)
    setDraftQuery(state.q)
  }
  useEffect(() => {
    if (draftQuery === state.q) return
    const timer = setTimeout(() => patch({ q: draftQuery }), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [draftQuery, state.q, patch])

  const range = useMemo(() => {
    if (state.view === 'week') {
      const start = sundayOf(state.day)
      return { start, end: shift(start, 6) }
    }
    if (state.view === 'month') {
      return { start: `${state.month}-01`, end: monthEnd(state.month) }
    }
    return { start: state.day, end: state.day }
  }, [state.view, state.day, state.month])

  const { channel, dept, cat, org, q, after, sort, group, view } = state

  useEffect(() => {
    if (view === 'settings') return
    const controller = new AbortController()
    void (async () => {
      setLoading(true)
      setError('')
      try {
        const result = await fetchEvents(
          { ...range, channel, dept, cat, org, q, after, sort, group },
          controller.signal,
        )
        setData(result)
      } catch (err: unknown) {
        if (controller.signal.aborted) return
        setError(err instanceof Error ? err.message : 'Request failed')
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    // Cancels the in-flight request when filters change again mid-flight.
    return () => controller.abort()
  }, [range, channel, dept, cat, org, q, after, sort, group, view])

  // Poll only while a refresh is actually running.
  useEffect(() => {
    if (!refreshing) return
    const timer = setInterval(() => {
      void fetchRefreshStatus().then((status) => {
        if (status.running) return
        setRefreshing(false)
        if (status.error) setNotice(`Refresh failed: ${status.error}`)
        else if (status.result?.errors?.length)
          setNotice('Updated what we could; some sources failed.')
        else setNotice('Loaded the next month of events.')
        patch({})
      })
    }, 2000)
    return () => clearInterval(timer)
  }, [refreshing, patch])

  const onRefresh = useCallback(async () => {
    setNotice('')
    try {
      await startRefresh()
      setRefreshing(true)
    } catch {
      setNotice('Could not start a refresh.')
    }
  }, [])

  const grouped = useMemo(() => {
    if (!data?.groups) return null
    const byId = new Map(data.events.map((event) => [event.id, event]))
    return data.groups.map((block) => ({
      ...block,
      events: block.ids.map((id) => byId.get(id)).filter((e) => e !== undefined),
    }))
  }, [data])

  const heading = useMemo(() => {
    if (view === 'settings') return 'Feeds'
    if (view === 'week') return `Week of ${new Date(`${range.start}T12:00:00`)
      .toLocaleDateString('en-US', { month: 'long', day: 'numeric' })}`
    if (view === 'month')
      return new Date(`${range.start}T12:00:00`)
        .toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
    return new Date(`${state.day}T12:00:00`)
      .toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
  }, [view, range.start, state.day])

  useEffect(() => {
    document.title = `${heading} · Yalendar`
  }, [heading])

  function stepDate(delta: number) {
    if (view === 'month') {
      const [year, monthNumber] = state.month.split('-').map(Number)
      const next = new Date(year, monthNumber - 1 + delta, 1)
      patch({ month: `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}` })
    } else {
      patch({ day: shift(state.day, view === 'week' ? 7 * delta : delta) })
    }
  }

  return (
    <>
      <header className="top">
        <div className="brand">
          <span className="yale-mark">Yale</span>
          <h1>Yalendar</h1>
          <p>Campus events for Yale students</p>
        </div>
        <nav>
          {NAV.map((name) => (
            <button
              key={name}
              type="button"
              className={view === name ? 'on' : ''}
              onClick={() => patch({ view: name })}
            >
              {name === 'settings' ? 'Feeds' : name[0].toUpperCase() + name.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      <main>
        <div className="layout with-chat">
          <aside className={`filters${filtersOpen ? ' open' : ''}`}>
            <button
              type="button"
              className="filter-toggle-label"
              aria-expanded={filtersOpen}
              onClick={() => setFiltersOpen((v) => !v)}
            >
              Date &amp; search
            </button>
            <div className="filter-panel">
            <span className="field-label">Date</span>
            <div className="date-nav">
              <button type="button" className="ghost" aria-label="Previous" onClick={() => stepDate(-1)}>‹</button>
              <input
                type="date"
                aria-label="Date"
                value={state.day}
                onChange={(event) =>
                  patch({ day: event.target.value, month: event.target.value.slice(0, 7) })
                }
              />
              <button type="button" className="ghost" aria-label="Next" onClick={() => stepDate(1)}>›</button>
            </div>
            <button
              type="button"
              className="today-link"
              onClick={() => patch({ day: todayIso(), month: todayIso().slice(0, 7) })}
            >
              Jump to today
            </button>

            <MiniMonth
              month={state.month}
              selected={state.day}
              today={data?.today ?? todayIso()}
              weekStart={view === 'week' ? range.start : undefined}
              onPick={(iso) => patch({ day: iso, month: iso.slice(0, 7) })}
              onMonth={(month) => patch({ month })}
            />

            <label className="field-label" htmlFor="search-input">Search</label>
            <input
              id="search-input"
              type="search"
              value={draftQuery}
              placeholder="Talk, club, place…"
              onChange={(event) => setDraftQuery(event.target.value)}
            />

            <label className="field-label" htmlFor="org-select">Organization</label>
            <select
              id="org-select"
              value={org[0] ?? ''}
              onChange={(event) => patch({ org: event.target.value ? [event.target.value] : [] })}
            >
              <option value="">All organizations</option>
              {data?.facets.orgs.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>

            <label className="field-label" htmlFor="sort-select">Sort</label>
            <select
              id="sort-select"
              value={sort}
              onChange={(event) => patch({ sort: event.target.value })}
            >
              {SORTS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>

            <label className="field-label" htmlFor="group-select">Group list by</label>
            <select
              id="group-select"
              value={group}
              onChange={(event) => patch({ group: event.target.value })}
            >
              {GROUPS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>

            <p className="hint">
              Gold = Campus Groups (SOM), separate from Yale Connect. Listings cover about
              a month of public Yale, Connect, Campus Groups and New Haven events.
            </p>
            </div>
          </aside>

          <section className="feed">
            <div className="meta-row">
              <div>
                <h2>{heading}</h2>
                <p>
                  {view === 'settings'
                    ? 'Extra ICS sources'
                    : loading
                      ? 'Loading…'
                      : data
                        ? `${data.count} of ${data.total} event${data.total === 1 ? '' : 's'}`
                        : ''}
                </p>
              </div>
              <button type="button" className="ghost" disabled={refreshing} onClick={onRefresh}>
                {refreshing ? 'Refreshing…' : 'Refresh one month'}
              </button>
            </div>

            {notice && <p className="banner">{notice}</p>}
            {error && <p className="error">Could not reach the calendar: {error}</p>}

            {view === 'settings' ? (
              <Settings />
            ) : (
              <>
                <TimeSlider value={after} onChange={(next) => patch({ after: next })} />

                {data && (
                  <>
                    <Chips
                      label="Source"
                      options={data.facets.channels}
                      selected={channel}
                      onToggle={(slug) => toggleIn('channel', slug)}
                      onClear={() => patch({ channel: [] })}
                      tintPrefix="ch-"
                    />
                    <Chips
                      label="School / department"
                      options={data.facets.departments}
                      selected={dept}
                      onToggle={(slug) => toggleIn('dept', slug)}
                      onClear={() => patch({ dept: [] })}
                    />
                    <Chips
                      label="Topic"
                      options={data.facets.categories}
                      selected={cat}
                      onToggle={(slug) => toggleIn('cat', slug)}
                      onClear={() => patch({ cat: [] })}
                      tintPrefix="cat-"
                    />
                  </>
                )}

                {data && view === 'day' && (
                  grouped
                    ? grouped.map((block) => (
                        <section className="cat-block" key={block.slug}>
                          <h3 className="cat-head">{block.label} <span>{block.count}</span></h3>
                          <EventList events={block.events} />
                        </section>
                      ))
                    : <EventList events={data.events} />
                )}
                {data && view === 'week' && (
                  <WeekGrid start={range.start} events={data.events} today={data.today} />
                )}
                {data && view === 'month' && (
                  <MonthGrid month={state.month} events={data.events} today={data.today} />
                )}
              </>
            )}
          </section>

          <AskPanel />
        </div>
      </main>
    </>
  )
}
