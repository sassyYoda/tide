export type ScoreBand = "high" | "mid" | "low" | "unknown"

/**
 * Map a numeric activity score to one of three pin shapes.
 * Thresholds (locked, see PATTERNS.md SpotPinLayer entry):
 *   score >= 0.7 → high  (circle, teal-700)
 *   0.4 <= score < 0.7 → mid (square, yellow-500)
 *   score < 0.4 → low (triangle, red-700)
 *   score === null → unknown (cold spot — Plan 03 emits no pin for these)
 */
export function scoreBand(score: number | null | undefined): ScoreBand {
  if (score == null) return "unknown"
  if (score >= 0.7) return "high"
  if (score >= 0.4) return "mid"
  return "low"
}

export const BAND_TO_SHAPE: Record<ScoreBand, "circle" | "square" | "triangle" | null> = {
  high: "circle",
  mid: "square",
  low: "triangle",
  unknown: null,
}

export const BAND_TO_LABEL: Record<ScoreBand, string> = {
  high: "High",
  mid: "Moderate",
  low: "Low",
  unknown: "unknown",
}
