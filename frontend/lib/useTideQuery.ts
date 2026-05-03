"use client"
import { useCallback, useReducer, useRef, useTransition } from "react"
import { createParser, type EventSourceMessage } from "eventsource-parser"
import { apiUrl } from "./api-client"
import type {
  RecommendationPayload,
  PartialConditionsPayload,
  ProgressStage,
  SSEErrorCode,
} from "./api-types"

export type {
  RecommendationPayload,
  PartialConditionsPayload,
  ProgressStage,
  SSEErrorCode,
}

export type LocationHint = { lat?: number; lon?: number; spot_name?: string }

export type TideQueryState =
  | { phase: "idle" }
  | { phase: "connecting" }
  | { phase: "streaming"; stage: ProgressStage; partial?: PartialConditionsPayload }
  | { phase: "done"; recommendation: RecommendationPayload }
  | { phase: "error"; code: SSEErrorCode; message: string }

type Action =
  | { type: "start" }
  | { type: "progress"; stage: ProgressStage }
  | { type: "partial_conditions"; payload: PartialConditionsPayload }
  | { type: "recommendation"; payload: RecommendationPayload }
  | { type: "error"; code: SSEErrorCode; message: string }
  | { type: "reset" }

function reducer(s: TideQueryState, a: Action): TideQueryState {
  switch (a.type) {
    case "start":
      return { phase: "connecting" }
    case "progress": {
      // PATTERNS.md MANDATORY note: idempotent on same-stage transitions
      // (route emits progress(planner) AND runtime emits progress(planner)
      // — see backend/api/v1/query.py lines 4-11).
      if (s.phase === "streaming" && s.stage === a.stage) return s
      // Preserve any partial_conditions captured in a prior streaming state
      const partial = s.phase === "streaming" ? s.partial : undefined
      return { phase: "streaming", stage: a.stage, partial }
    }
    case "partial_conditions":
      // Carry partial in state so RecommendationCard skeleton can render early
      if (s.phase === "streaming") return { ...s, partial: a.payload }
      return { phase: "streaming", stage: "data_fetcher", partial: a.payload }
    case "recommendation":
      return { phase: "done", recommendation: a.payload }
    case "error":
      return { phase: "error", code: a.code, message: a.message }
    case "reset":
      return { phase: "idle" }
  }
}

export function useTideQuery() {
  const [state, dispatch] = useReducer(reducer, { phase: "idle" } as TideQueryState)
  const [isPending, startTransition] = useTransition()
  const abortRef = useRef<AbortController | null>(null)

  const submit = useCallback(async (query: string, hint?: LocationHint) => {
    // Pre-fetch validation — mirrors backend QueryBody.max_length=500 (PATTERNS source 2)
    if (query.length === 0) {
      dispatch({ type: "error", code: "internal", message: "Query is required" })
      return
    }
    if (query.length > 500) {
      dispatch({ type: "error", code: "internal", message: "Query exceeds 500 character limit" })
      return
    }

    // Abort any in-flight stream before starting a new one
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac

    dispatch({ type: "start" })

    let resp: Response
    try {
      resp = await fetch(apiUrl("/api/v1/query"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, location_hint: hint ?? null }),
        signal: ac.signal,
      })
    } catch {
      if (ac.signal.aborted) return
      dispatch({ type: "error", code: "internal", message: "Network failure" })
      return
    }

    if (!resp.ok || !resp.body) {
      dispatch({ type: "error", code: "internal", message: `Network failure (${resp.status})` })
      return
    }

    const parser = createParser({
      onEvent(ev: EventSourceMessage) {
        let data: unknown
        try {
          data = JSON.parse(ev.data)
        } catch {
          return
        }
        startTransition(() => {
          if (ev.event === "progress") {
            dispatch({ type: "progress", stage: (data as { stage: ProgressStage }).stage })
          } else if (ev.event === "partial_conditions") {
            dispatch({ type: "partial_conditions", payload: data as PartialConditionsPayload })
          } else if (ev.event === "recommendation") {
            dispatch({ type: "recommendation", payload: data as RecommendationPayload })
          } else if (ev.event === "error") {
            const e = data as { code: SSEErrorCode; message: string }
            dispatch({ type: "error", code: e.code, message: e.message })
          }
        })
      },
    })

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        parser.feed(decoder.decode(value, { stream: true }))
      }
    } catch {
      if (!ac.signal.aborted) {
        dispatch({ type: "error", code: "internal", message: "Stream interrupted" })
      }
    }
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    dispatch({ type: "reset" })
  }, [])

  return { state, submit, reset, isPending }
}
