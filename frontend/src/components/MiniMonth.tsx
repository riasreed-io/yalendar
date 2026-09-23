import { memo, useMemo } from 'react'

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S']

function isoOf(day: Date): string {
  const month = String(day.getMonth() + 1).padStart(2, '0')
  const date = String(day.getDate()).padStart(2, '0')
  return `${day.getFullYear()}-${month}-${date}`
}

type Props = {
  month: string
  selected: string
  today: string
  weekStart?: string
  onPick: (iso: string) => void
  onMonth: (month: string) => void
}

function MiniMonth({ month, selected, today, weekStart, onPick, onMonth }: Props) {
  const [year, monthNumber] = month.split('-').map(Number)

  const weeks = useMemo(() => {
    const first = new Date(year, monthNumber - 1, 1)
    const cursor = new Date(first)
    cursor.setDate(1 - first.getDay())
    const out: Date[][] = []
    for (let w = 0; w < 6; w += 1) {
      const row: Date[] = []
      for (let d = 0; d < 7; d += 1) {
        row.push(new Date(cursor))
        cursor.setDate(cursor.getDate() + 1)
      }
      out.push(row)
      if (cursor.getMonth() !== monthNumber - 1 && cursor.getDate() > 7) break
    }
    return out
  }, [year, monthNumber])

  const inWeek = useMemo(() => {
    if (!weekStart) return new Set<string>()
    const start = new Date(`${weekStart}T12:00:00`)
    return new Set(
      Array.from({ length: 7 }, (_, i) => {
        const day = new Date(start)
        day.setDate(day.getDate() + i)
        return isoOf(day)
      }),
    )
  }, [weekStart])

  const label = new Date(year, monthNumber - 1, 1).toLocaleDateString('en-US', {
    month: 'long', year: 'numeric',
  })

  function step(delta: number) {
    const next = new Date(year, monthNumber - 1 + delta, 1)
    onMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`)
  }

  return (
    <div className="mini">
      <div className="mini-head">
        <button type="button" className="ghost" aria-label="Previous month" onClick={() => step(-1)}>‹</button>
        <span>{label}</span>
        <button type="button" className="ghost" aria-label="Next month" onClick={() => step(1)}>›</button>
      </div>
      <div className="mini-grid" role="grid">
        {WEEKDAYS.map((name, i) => (
          <div className="mini-wd" key={`${name}-${i}`}>{name}</div>
        ))}
        {weeks.flat().map((day) => {
          const iso = isoOf(day)
          const classes = [
            'mini-day',
            day.getMonth() === monthNumber - 1 ? '' : 'out',
            iso === today ? 'today' : '',
            iso === selected ? 'sel' : '',
            inWeek.has(iso) ? 'inweek' : '',
          ].filter(Boolean).join(' ')
          return (
            <button type="button" className={classes} key={iso} onClick={() => onPick(iso)}>
              {day.getDate()}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default memo(MiniMonth)
