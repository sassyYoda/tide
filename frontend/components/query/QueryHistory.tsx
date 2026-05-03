"use client"
interface Props {
  list: string[]
  onPick: (query: string) => void
}

export function QueryHistory({ list, onPick }: Props) {
  if (list.length === 0) return null
  return (
    <div data-testid="query-history" className="flex flex-wrap items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-stone-500">Recent:</span>
      {list.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onPick(q)}
          className="max-w-xs truncate rounded-full border border-stone-300 bg-white px-3 py-1 text-xs text-stone-700 hover:border-tide-high hover:text-tide-high"
          data-testid="history-chip"
        >
          {q}
        </button>
      ))}
    </div>
  )
}
