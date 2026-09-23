import { useCallback, useEffect, useState } from 'react'

export type View = 'day' | 'week' | 'month' | 'settings'

export type UiState = {
  view: View
  day: string
  month: string
  channel: string[]
  dept: string[]
  cat: string[]
  org: string[]
  q: string
  after: string
  sort: string
  group: string
}

const VIEWS: View[] = ['day', 'week', 'month', 'settings']

export function todayIso(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const date = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${date}`
}

function parse(search: string): UiState {
  const p = new URLSearchParams(search)
  const view = p.get('view')
  const day = p.get('day') || todayIso()
  return {
    view: VIEWS.includes(view as View) ? (view as View) : 'day',
    day,
    month: p.get('month') || day.slice(0, 7),
    channel: p.getAll('channel'),
    dept: p.getAll('dept'),
    cat: p.getAll('cat'),
    org: p.getAll('org'),
    q: p.get('q') ?? '',
    after: p.get('after') ?? 'all',
    sort: p.get('sort') ?? 'time',
    group: p.get('group') ?? 'none',
  }
}

function serialize(state: UiState): string {
  const p = new URLSearchParams()
  if (state.view !== 'day') p.set('view', state.view)
  if (state.day !== todayIso()) p.set('day', state.day)
  if (state.view === 'month') p.set('month', state.month)
  for (const slug of state.channel) p.append('channel', slug)
  for (const slug of state.dept) p.append('dept', slug)
  for (const slug of state.cat) p.append('cat', slug)
  for (const name of state.org) p.append('org', name)
  if (state.q) p.set('q', state.q)
  if (state.after !== 'all') p.set('after', state.after)
  if (state.sort !== 'time') p.set('sort', state.sort)
  if (state.group !== 'none') p.set('group', state.group)
  return p.toString()
}

/** Keeps the whole UI in the query string, so any view can be copied and shared
 *  the way the server-rendered pages already could. */
export function useUrlState() {
  const [state, setState] = useState<UiState>(() => parse(window.location.search))

  useEffect(() => {
    const query = serialize(state)
    const next = `${window.location.pathname}${query ? `?${query}` : ''}`
    if (next !== window.location.pathname + window.location.search) {
      window.history.replaceState(null, '', next)
    }
  }, [state])

  useEffect(() => {
    const onPop = () => setState(parse(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const patch = useCallback((changes: Partial<UiState>) => {
    setState((prev) => ({ ...prev, ...changes }))
  }, [])

  const toggleIn = useCallback(
    (key: 'channel' | 'dept' | 'cat' | 'org', slug: string) => {
      setState((prev) => {
        const current = prev[key]
        return {
          ...prev,
          [key]: current.includes(slug)
            ? current.filter((s) => s !== slug)
            : [...current, slug],
        }
      })
    },
    [],
  )

  return { state, patch, toggleIn }
}
