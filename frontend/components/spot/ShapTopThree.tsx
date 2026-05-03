"use client"

interface Props {
  shap: string[] | null // NOTE: NOT optional, NOT `[]` — null signals empty-state
}

export function ShapTopThree({ shap }: Props) {
  // F-16 honest empty branch: null means the URL didn't carry shap context.
  // Do NOT render an empty <ol>. Do NOT pretend there's data.
  if (shap === null || shap.length === 0) {
    return (
      <section
        data-testid="shap-empty"
        className="rounded-md border border-stone-300 bg-stone-50 p-3 text-sm text-stone-600"
      >
        <p className="font-medium">No reasoning context for this view.</p>
        <p className="mt-1 text-xs">
          Ask Tide a question first — the top-3 features driving the score
          flow into this page via the recommendation link.
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="shap-top-three"
      className="rounded-md border border-stone-200 bg-white p-3"
    >
      <h3 className="font-display text-sm uppercase tracking-wide text-stone-700">
        Top features driving this score
      </h3>
      <ol className="mt-2 ml-5 list-decimal space-y-1 text-sm text-stone-800">
        {shap.slice(0, 3).map((feat) => (
          <li key={feat}>{feat}</li>
        ))}
      </ol>
    </section>
  )
}
