"use client"
import type { TideQueryState, ProgressStage } from "@/lib/useTideQuery"

const STAGE_LABEL: Record<ProgressStage, string> = {
  planner: "Planning your query…",
  data_fetcher: "Fetching live conditions…",
  rag_retriever: "Searching local reports…",
  synthesizer: "Synthesizing recommendation…",
}

interface Props {
  state: TideQueryState
}

export function QueryProgress({ state }: Props) {
  if (state.phase === "idle") return null
  if (state.phase === "connecting") {
    return (
      <div role="status" aria-live="polite" className="text-stone-700">
        Connecting…
      </div>
    )
  }
  if (state.phase === "streaming") {
    return (
      <div
        role="status"
        aria-live="polite"
        data-testid="query-progress"
        className="flex items-center gap-2 text-stone-700"
      >
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-tide-high" />
        <span>{STAGE_LABEL[state.stage]}</span>
      </div>
    )
  }
  // error and done are rendered by parent — error via ERROR_COPY map, done via card
  return null
}
