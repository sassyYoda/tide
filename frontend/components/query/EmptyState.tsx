"use client"

const COPY = "Not enough recent local reports to recommend a spot — try widening to whole bay"

export function EmptyState() {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="empty-state"
      className="rounded-md border border-stone-300 bg-stone-50 p-4 text-sm text-stone-700"
    >
      <p className="font-display text-lg text-stone-900">No solid lead yet</p>
      <p className="mt-1">{COPY}</p>
    </div>
  )
}
