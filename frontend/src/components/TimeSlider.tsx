import { useState } from 'react'

const MARKS = ['12 am', '4 am', '8 am', '12 pm', '4 pm', '8 pm']

function hourLabel(hour: number): string {
  const suffix = hour < 12 ? 'AM' : 'PM'
  return `${hour % 12 || 12}:00 ${suffix}`
}

type Props = {
  value: string // "all" or "HH:00"
  onChange: (next: string) => void
}

// One-hour steps, with a live readout while dragging; the filter only
// applies on release.
export default function TimeSlider({ value, onChange }: Props) {
  const allTimes = value === 'all'
  const parsed = allTimes ? 0 : Number(value.slice(0, 2))
  // Adjust the in-flight draft when the applied value changes, during render
  // rather than in an effect, so there is no extra render pass.
  const [draft, setDraft] = useState(parsed)
  const [seen, setSeen] = useState(value)
  if (value !== seen) {
    setSeen(value)
    setDraft(parsed)
  }

  return (
    <div className="time-row">
      <div className="time-head">
        <button
          type="button"
          className={`chip${allTimes ? ' on' : ''}`}
          onClick={() => onChange('all')}
        >
          All times
        </button>
        <span className="time-readout">
          {allTimes ? 'Showing the full day' : `From ${hourLabel(draft)}`}
        </span>
      </div>
      <div className={`slider-wrap${allTimes ? ' dim' : ''}`}>
        <input
          type="range"
          min={0}
          max={23}
          step={1}
          value={draft}
          aria-label="Show events starting at or after this hour"
          aria-valuetext={`From ${hourLabel(draft)}`}
          onChange={(e) => setDraft(Number(e.target.value))}
          onMouseUp={() => onChange(`${String(draft).padStart(2, '0')}:00`)}
          onTouchEnd={() => onChange(`${String(draft).padStart(2, '0')}:00`)}
          onKeyUp={() => onChange(`${String(draft).padStart(2, '0')}:00`)}
        />
        <div className="ticks">
          {MARKS.map((mark) => (
            <span key={mark}>{mark}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
