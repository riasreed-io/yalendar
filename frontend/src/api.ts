// Plain fetch against the FastAPI backend. No client library, no state library.

const BASE = (import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8002').replace(/\/$/, '')

export type Event = {
  id: string
  title: string
  start: string
  all_day: boolean
  location: string
  org: string
  url: string
  description: string
  source: string
  channel: string
  channel_label: string
  category: string
  category_label: string
  dept: string
  dept_label: string
  also_listed: string[]
}

export type Facet = { slug: string; label: string; count: number }

export type Facets = {
  channels: Facet[]
  departments: Facet[]
  categories: Facet[]
  orgs: string[]
}

export type EventsResponse = {
  start: string
  end: string
  today: string
  total: number
  count: number
  events: Event[]
  facets: Facets
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

export type Health = {
  ok: boolean
  today: string
  events: number
  data_from: string | null
  data_through: string | null
}

async function get<T>(path: string, params?: URLSearchParams): Promise<T> {
  const url = params ? `${BASE}${path}?${params}` : `${BASE}${path}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
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
  q?: string
  after?: string
}

export function fetchEvents(query: EventQuery): Promise<EventsResponse> {
  const params = new URLSearchParams({ start: query.start, end: query.end })
  for (const slug of query.channel ?? []) params.append('channel', slug)
  for (const slug of query.dept ?? []) params.append('dept', slug)
  for (const slug of query.cat ?? []) params.append('cat', slug)
  if (query.q) params.set('q', query.q)
  params.set('after', query.after ?? 'all')
  return get<EventsResponse>('/api/events', params)
}

export function fetchHealth(): Promise<Health> {
  return get<Health>('/api/health')
}

export function fetchAgentStatus(): Promise<AgentStatus> {
  return get<AgentStatus>('/api/agent/status')
}

// Routes to the model-backed agent when it is available, otherwise the free
// local search. The backend decides and reports which ran via `engine`.
export function ask(question: string, useAgent: boolean): Promise<AskResponse> {
  return post<AskResponse>(useAgent ? '/api/agent' : '/api/ask', { q: question })
}
