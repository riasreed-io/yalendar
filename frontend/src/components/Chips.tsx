import type { Facet } from '../api'

type Props = {
  label: string
  options: Facet[]
  selected: string[]
  onToggle: (slug: string) => void
  onClear: () => void
  colorBySlug?: boolean
}

// Multi-select: OR within a row, AND across rows. Clicking a selected chip
// removes it; "All" clears the row.
export default function Chips({
  label,
  options,
  selected,
  onToggle,
  onClear,
  colorBySlug = false,
}: Props) {
  return (
    <div className="chip-row">
      <p className="chip-label">{label}</p>
      <div className="chips">
        <button
          type="button"
          className={`chip${selected.length === 0 ? ' on' : ''}`}
          onClick={onClear}
        >
          All
        </button>
        {options.map((option) => {
          const on = selected.includes(option.slug)
          const tint = colorBySlug ? ` ch-${option.slug}` : ''
          return (
            <button
              key={option.slug}
              type="button"
              className={`chip${tint}${on ? ' on' : ''}`}
              aria-pressed={on}
              onClick={() => onToggle(option.slug)}
            >
              {option.label} <em>{option.count}</em>
            </button>
          )
        })}
      </div>
    </div>
  )
}
