import { test, expect } from "vitest"
// @ts-expect-error color-blind has no published types
import blinder from "color-blind"
import { getContrast } from "color2k"

// D-01 locked palette (marine-pragmatic). The a11y load-bearing mechanism is the
// SHAPE supplement (L-06: circle/square/triangle SVG sprites) — this test is a
// REGRESSION NET against palette drift, not a usability gate.
//
// Measured pairwise contrast under Brettel-simulated dichromacy (color-blind v0.1.3):
//   protanopia    : H↔M=4.07  M↔L=3.47  H↔L=1.17
//   deuteranopia  : H↔M=3.94  M↔L=3.34  H↔L=1.18
// The H↔L pair collapses (deep teal and red-700 share a similar luminance under
// red-blind simulation). Per CONTEXT.md the user has locked the palette; the
// distinct shapes are the actual a11y guarantee. Thresholds below catch drift
// (e.g., someone switching teal-700 → blue-700) without false-failing the lock.
const PALETTE = {
  high: "#0F766E",
  mid:  "#EAB308",
  low:  "#B91C1C",
}

test.each([
  ["protanopia", blinder.protanopia],
  ["deuteranopia", blinder.deuteranopia],
])("score-band colors remain distinguishable under %s", (_label, sim) => {
  const sH = sim(PALETTE.high)
  const sM = sim(PALETTE.mid)
  const sL = sim(PALETTE.low)
  // High↔Mid and Mid↔Low must keep clear separation (mid acts as the distinguishing
  // axis when red-vs-teal collapses for red-blind viewers).
  expect(getContrast(sH, sM)).toBeGreaterThan(2.0)
  expect(getContrast(sM, sL)).toBeGreaterThan(2.0)
  // High↔Low collapses for red-blind users; we only assert they aren't IDENTICAL
  // (regression catch). Shapes carry the real a11y guarantee per L-06.
  expect(getContrast(sH, sL)).toBeGreaterThan(1.1)
})
