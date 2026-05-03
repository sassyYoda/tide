"use client"

const COPY =
  "We don't have a recommendation context for this spot yet. Try asking Tide a question first — recommendations carry forward into spot detail."

export function SpotEmptyState({ spotName }: { spotName: string | null }) {
  return (
    <section
      role="status"
      data-testid="spot-empty-state"
      className="rounded-lg border border-stone-300 bg-tide-surface p-5"
    >
      <h2 className="font-display text-2xl text-tide-high">
        {spotName ?? "This spot"}
      </h2>
      <p className="mt-3 text-sm text-stone-700">{COPY}</p>
      <a
        href="/"
        className="mt-3 inline-block text-sm text-tide-high underline-offset-2 hover:underline"
      >
        Ask Tide a question →
      </a>
    </section>
  )
}
