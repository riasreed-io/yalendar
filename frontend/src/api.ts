// Plain fetch against the FastAPI backend. No client library, no state library.

const BASE = (import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8002').replace(/\/$/, '')

// List rows omit `description` — it was ~46% of the payload and is only shown
// when a row is expanded, so it is fetched per event from /api/events/{id}.
export type Event = {
  id: string
  title: string
  start: string
  all_day: boolean
  location: string
  org: string
  url: string
  source: string
  channel: string
  channel_label: string
  category: string
  category_label: string
  dept: string
  dept_label: string
  also_listed: string[]
  has_description: boolean
}

export type EventDetail = Event & { description: string; tags: string; end: string }

export type Facet = { slug: string; label: string; count: number }
export type Facets = {
  channels: Facet[]
  departments: Facet[]
  categories: Facet[]
  orgs: string[]
}
export type Group = { slug: string; label: string; count: number; ids: string[] }

export type EventsResponse = {
  start: string
  end: string
  today: string
  total: number
  count: number
  events: Event[]
  facets: Facets
  groups?: Group[]
}

export type AskHit = {
  title: string
  when: string
  location: string
  org: string
  url: string
  channel: string
}

export type AskResponse = {
  reply: string
  events: AskHit[]
  more: number
  link: string
  link_label: string
  suggestions: string[]
  engine: 'local' | 'agent'
  note?: string
  tools_used?: string[]
}

export type AgentStatus = { allowed: boolean; configured: boolean; public: boolean }
export type RefreshStatus = {
  running: boolean
  finished_at: string | null
  result: { upserted: number | null; errors: string[] } | null
  error: string | null
}

async function get<T>(path: string, params?: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const res = await fetch(params ? `${BASE}${path}?${params}` : `${BASE}${path}`, { signal })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

async function send<T>(path: string, method: 'POST' | 'PUT', body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

export type EventQuery = {
  start: string
  end: string
  channel?: string[]
  dept?: string[]
  cat?: string[]
  org?: string[]
  q?: string
  after?: string
  sort?: string
  group?: string
}

export function buildEventParams(query: EventQuery): URLSearchParams {
  const params = new URLSearchParams({ start: query.start, end: query.end })
  for (const slug of query.channel ?? []) params.append('channel', slug)
  for (const slug of query.dept ?? []) params.append('dept', slug)
  for (const slug of query.cat ?? []) params.append('cat', slug)
  for (const name of query.org ?? []) params.append('org', name)
  if (query.q) params.set('q', query.q)
  params.set('after', query.after ?? 'all')
  if (query.sort && query.sort !== 'time') params.set('sort', query.sort)
  if (query.group && query.group !== 'none') params.set('group', query.group)
  return params
}

export function fetchEvents(query: EventQuery, signal?: AbortSignal): Promise<EventsResponse> {
  return get<EventsResponse>('/api/events', buildEventParams(query), signal)
}

export function fetchEventDetail(id: string, signal?: AbortSignal): Promise<EventDetail> {
  return get<EventDetail>(`/api/events/${encodeURIComponent(id)}`, undefined, signal)
}

export function fetchAgentStatus(): Promise<AgentStatus> {
  return get<AgentStatus>('/api/agent/status')
}

export function startRefresh(): Promise<{ started: boolean; running: boolean }> {
  return send('/api/refresh', 'POST', {})
}

export function fetchRefreshStatus(): Promise<RefreshStatus> {
  return get<RefreshStatus>('/api/refresh/status')
}

export function fetchFeeds(): Promise<{ urls: string[] }> {
  return get<{ urls: string[] }>('/api/feeds')
}

export function saveFeeds(urls: string[]): Promise<{ urls: string[]; saved: number }> {
  return send('/api/feeds', 'PUT', { urls })
}

// The backend decides which engine runs and reports it back via `engine`.
export function ask(question: string, useAgent: boolean): Promise<AskResponse> {
  return send<AskResponse>(useAgent ? '/api/agent' : '/api/ask', 'POST', { q: question })
}
