"use client"
export type Species = "striper" | "fluke" | "bluefish" | "weakfish" | "tautog"

interface Props {
  all: Species[]
  selected: Species[]
  onChange: (next: Species[]) => void
}

export function SpeciesFilter({ all, selected, onChange }: Props) {
  const toggle = (s: Species) => {
    onChange(selected.includes(s) ? selected.filter((x) => x !== s) : [...selected, s])
  }
  return (
    <div
      role="group"
      aria-label="Species filter"
      className="absolute left-3 top-3 z-10 flex flex-col gap-1 rounded-md bg-white/95 p-2 shadow"
    >
      {all.map((s) => {
        const checked = selected.includes(s)
        return (
          <label key={s} className="flex cursor-pointer items-center gap-2 text-sm text-stone-900">
            <input
              type="checkbox"
              checked={checked}
              onChange={() => toggle(s)}
              aria-label={`Toggle ${s}`}
              data-testid={`species-${s}`}
            />
            <span className="capitalize">{s}</span>
          </label>
        )
      })}
    </div>
  )
}
