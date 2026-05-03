"use client"
import { useCallback, useEffect, useState } from "react"

const HISTORY_KEY = "tide.history.last5"
const MAX = 5

function readStorage(): string[] {
  if (typeof window === "undefined") return []
  try {
    // P7: sessionStorage ONLY — never the other-Storage variant (L-14)
    const raw = window.sessionStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((x): x is string => typeof x === "string").slice(0, MAX)
  } catch {
    return []
  }
}

function writeStorage(list: string[]): void {
  if (typeof window === "undefined") return
  try {
    window.sessionStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, MAX)))
  } catch {
    /* quota / private mode — silently no-op */
  }
}

export function useSessionHistory() {
  const [list, setList] = useState<string[]>([])

  useEffect(() => {
    setList(readStorage())
  }, [])

  const add = useCallback((q: string) => {
    const trimmed = q.trim()
    if (!trimmed) return
    setList((prev) => {
      const deduped = [trimmed, ...prev.filter((x) => x !== trimmed)].slice(0, MAX)
      writeStorage(deduped)
      return deduped
    })
  }, [])

  const clear = useCallback(() => {
    writeStorage([])
    setList([])
  }, [])

  return { list, add, clear }
}
