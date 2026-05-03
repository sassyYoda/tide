"use client"
import { useTideQuery, type SSEErrorCode } from "@/lib/useTideQuery"
import { useSessionHistory } from "@/lib/useSessionHistory"
import { QueryInput } from "@/components/query/QueryInput"
import { QueryProgress } from "@/components/query/QueryProgress"
import { QueryHistory } from "@/components/query/QueryHistory"
import { RecommendationCard } from "@/components/query/RecommendationCard"

const ERROR_COPY: Record<SSEErrorCode, string> = {
  rate_limited: "You've hit the 20-queries-per-hour limit. Try again in an hour.",
  planner_timeout: "That took too long to plan. Try a simpler query.",
  planner_out_of_scope:
    "That's outside Tide's scope (saltwater NJ, 5 species). Try: stripers at Barnegat this weekend.",
  llm_unavailable: "Recommendation engine is briefly unavailable. Try again in a moment.",
  internal: "Something went wrong. The team's been notified.",
}

export default function HomePage() {
  const { state, submit, reset } = useTideQuery()
  const { list, add } = useSessionHistory()

  const handleSubmit = (q: string) => {
    add(q)
    submit(q)
  }

  const inFlight = state.phase === "connecting" || state.phase === "streaming"

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 pb-24 md:pb-8">
      <header className="mb-6">
        <h1 className="font-display text-4xl text-tide-high">Tide</h1>
        <p className="mt-1 text-lg text-stone-700">Hyper-local NJ saltwater fishing intel.</p>
      </header>

      <section className="mb-4">
        <QueryInput onSubmit={handleSubmit} disabled={inFlight} />
      </section>

      <section className="mb-4">
        <QueryHistory list={list} onPick={handleSubmit} />
      </section>

      <section
        className="min-h-[400px] rounded-lg border border-stone-200 bg-white p-4"
        data-testid="recommendation-area"
      >
        <QueryProgress state={state} />

        {state.phase === "error" && (
          <div role="alert" data-testid="query-error" className="text-sm text-tide-low">
            <p>{ERROR_COPY[state.code]}</p>
            <button onClick={reset} className="mt-2 text-xs text-stone-600 underline">
              Dismiss
            </button>
          </div>
        )}

        {state.phase === "done" && (
          <RecommendationCard recommendation={state.recommendation} />
        )}

        {state.phase === "idle" && (
          <p className="text-stone-500">Ask a question to see a cited, condition-aware recommendation.</p>
        )}
      </section>
    </main>
  )
}
