import { describe, expect, test, beforeEach } from "vitest"
import { renderHook, act, waitFor } from "@testing-library/react"
import { useSessionHistory } from "@/lib/useSessionHistory"

beforeEach(() => {
  window.sessionStorage.clear()
  window.localStorage.clear()
})

describe("useSessionHistory — L-14 / P7", () => {
  test("most-recent-first ordering, dedup, capped at 5", async () => {
    const { result } = renderHook(() => useSessionHistory())
    await waitFor(() => expect(result.current.list).toEqual([]))
    act(() => {
      result.current.add("query A")
    })
    act(() => {
      result.current.add("query B")
    })
    act(() => {
      result.current.add("query C")
    })
    act(() => {
      result.current.add("query A") // dedup → moves to front
    })
    act(() => {
      result.current.add("D")
    })
    act(() => {
      result.current.add("E")
    })
    act(() => {
      result.current.add("F")
    })
    expect(result.current.list).toHaveLength(5)
    expect(result.current.list[0]).toBe("F")
    // dedup: A appears once
    expect(result.current.list.filter((x) => x === "query A")).toHaveLength(1)
  })

  test("does NOT write to the other web-storage object (P7 enforcement)", async () => {
    const { result } = renderHook(() => useSessionHistory())
    await waitFor(() => expect(result.current.list).toEqual([]))
    act(() => {
      result.current.add("test")
    })
    // localStorage remains empty (the persistence layer is sessionStorage only)
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.getItem("tide.history.last5")).toBeTruthy()
  })

  test("survives module reload by re-reading sessionStorage", async () => {
    window.sessionStorage.setItem("tide.history.last5", JSON.stringify(["seeded"]))
    const { result } = renderHook(() => useSessionHistory())
    await waitFor(() => expect(result.current.list).toEqual(["seeded"]))
  })

  test("clear() empties the list and storage", async () => {
    const { result } = renderHook(() => useSessionHistory())
    await waitFor(() => expect(result.current.list).toEqual([]))
    act(() => {
      result.current.add("a")
    })
    act(() => {
      result.current.clear()
    })
    expect(result.current.list).toEqual([])
    expect(window.sessionStorage.getItem("tide.history.last5")).toBe("[]")
  })

  test("trims whitespace and ignores empty strings", async () => {
    const { result } = renderHook(() => useSessionHistory())
    await waitFor(() => expect(result.current.list).toEqual([]))
    act(() => {
      result.current.add("  spaced  ")
    })
    act(() => {
      result.current.add("")
    })
    act(() => {
      result.current.add("   ")
    })
    expect(result.current.list).toEqual(["spaced"])
  })
})
