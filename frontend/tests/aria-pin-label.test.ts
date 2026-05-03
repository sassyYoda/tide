import { describe, expect, test } from "vitest"
import { buildAriaPinLabel } from "@/lib/aria-pin-label"
import { scoreBand } from "@/lib/score-band"

describe("scoreBand", () => {
  test("classifies high/mid/low/unknown correctly", () => {
    expect(scoreBand(0.85)).toBe("high")
    expect(scoreBand(0.7)).toBe("high")
    expect(scoreBand(0.55)).toBe("mid")
    expect(scoreBand(0.4)).toBe("mid")
    expect(scoreBand(0.2)).toBe("low")
    expect(scoreBand(0)).toBe("low")
    expect(scoreBand(null)).toBe("unknown")
    expect(scoreBand(undefined)).toBe("unknown")
  })
})

describe("buildAriaPinLabel — L-08 sentence pattern", () => {
  test("happy path matches sentence verbatim", () => {
    expect(
      buildAriaPinLabel({ species: "striper", score: 0.81, dataAgeSeconds: 720, citationCount: 3 }),
    ).toBe("Striper pin: High confidence, 12 minutes old, 3 reports cited")
  })

  test("age bucketing: <1min, minutes, hours, days, unknown", () => {
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: 30, citationCount: 1 })).toContain("less than a minute old")
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: 7200, citationCount: 1 })).toContain("2 hours old")
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: 90000, citationCount: 1 })).toContain("1 day old")
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: null, citationCount: 1 })).toContain("age unknown")
  })

  test("citation pluralization", () => {
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: 60, citationCount: 0 })).toContain("no reports cited")
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: 60, citationCount: 1 })).toContain("1 report cited")
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: 60, citationCount: 5 })).toContain("5 reports cited")
  })

  test("unknown score → 'unknown confidence' phrase", () => {
    expect(buildAriaPinLabel({ species: "tautog", score: null, dataAgeSeconds: 60, citationCount: 0 })).toContain("unknown confidence")
  })

  test("species capitalization for canonical 5", () => {
    expect(buildAriaPinLabel({ species: "striper", score: 0.5, dataAgeSeconds: 60, citationCount: 0 })).toMatch(/^Striper pin:/)
    expect(buildAriaPinLabel({ species: "fluke", score: 0.5, dataAgeSeconds: 60, citationCount: 0 })).toMatch(/^Fluke pin:/)
    expect(buildAriaPinLabel({ species: null, score: 0.5, dataAgeSeconds: 60, citationCount: 0 })).toMatch(/^Unknown pin:/)
  })
})
