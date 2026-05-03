import recommendation from "./recommendation.json"

export function buildHappyPathSSE(): string {
  const events = [
    { event: "progress",            data: { stage: "planner" } },
    { event: "progress",            data: { stage: "data_fetcher" } },
    { event: "partial_conditions",  data: { spot_id: 7, spot_name: "Barnegat Inlet", ml_score: 0.81, shap_top3: ["a","b","c"], data_age_seconds: 420.0, conditions_stale: false, conditions: { wind_kt: 8.2 } } },
    { event: "progress",            data: { stage: "rag_retriever" } },
    { event: "progress",            data: { stage: "synthesizer" } },
    { event: "recommendation",      data: recommendation },
  ]
  return events.map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("")
}

export function buildErrorSSE(code: string, message: string): string {
  const ev = { event: "error", data: { code, message } }
  return `event: progress\ndata: {"stage":"planner"}\n\nevent: ${ev.event}\ndata: ${JSON.stringify(ev.data)}\n\n`
}

export function buildRateLimitSSE(): string {
  return buildErrorSSE("rate_limited", "You've hit the 20-queries-per-hour limit.")
}
