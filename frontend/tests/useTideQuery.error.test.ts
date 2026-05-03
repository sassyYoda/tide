import { describe, expect, test, vi, beforeEach } from "vitest"
import { renderHook, act, waitFor } from "@testing-library/react"
import { useTideQuery } from "@/lib/useTideQuery"
import { buildRateLimitSSE, buildErrorSSE } from "./fixtures/sse-stream"

function mockFetchWithSSE(body: string) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body))
      controller.close()
    },
  })
  return vi.fn().mockResolvedValue(
    new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
  )
}

beforeEach(() => {
  vi.unstubAllGlobals()
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000")
})

describe("useTideQuery — error events", () => {
  test("rate_limited surfaces as state.error with code+message", async () => {
    vi.stubGlobal("fetch", mockFetchWithSSE(buildRateLimitSSE()))
    const { result } = renderHook(() => useTideQuery())
    await act(async () => {
      await result.current.submit("test")
    })
    await waitFor(() => expect(result.current.state.phase).toBe("error"))
    if (result.current.state.phase !== "error") throw new Error("not error")
    expect(result.current.state.code).toBe("rate_limited")
    expect(result.current.state.message).toContain("20-queries-per-hour")
  })

  test("planner_out_of_scope surfaces verbatim", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchWithSSE(buildErrorSSE("planner_out_of_scope", "Out of scope")),
    )
    const { result } = renderHook(() => useTideQuery())
    await act(async () => {
      await result.current.submit("trout")
    })
    await waitFor(() => expect(result.current.state.phase).toBe("error"))
    if (result.current.state.phase !== "error") throw new Error("not error")
    expect(result.current.state.code).toBe("planner_out_of_scope")
  })

  test("network failure → error{code:'internal'}", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
    const { result } = renderHook(() => useTideQuery())
    await act(async () => {
      await result.current.submit("test")
    })
    await waitFor(() => expect(result.current.state.phase).toBe("error"))
    if (result.current.state.phase !== "error") throw new Error("not error")
    expect(result.current.state.code).toBe("internal")
  })

  test("non-OK response → error{code:'internal'}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("nope", { status: 500 })),
    )
    const { result } = renderHook(() => useTideQuery())
    await act(async () => {
      await result.current.submit("test")
    })
    await waitFor(() => expect(result.current.state.phase).toBe("error"))
    if (result.current.state.phase !== "error") throw new Error("not error")
    expect(result.current.state.code).toBe("internal")
    expect(result.current.state.message).toContain("500")
  })
})
