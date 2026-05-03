import { BAND_TO_LABEL, scoreBand } from "./score-band"

interface AriaPinInput {
  species: string | null | undefined
  score: number | null | undefined
  dataAgeSeconds: number | null | undefined
  citationCount: number
}

function capitalize(s: string): string {
  return s.length === 0 ? s : s[0]!.toUpperCase() + s.slice(1).toLowerCase()
}

function humanAge(seconds: number | null | undefined): string {
  if (seconds == null) return "age unknown"
  if (seconds < 60) return "less than a minute old"
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} ${minutes === 1 ? "minute" : "minutes"} old`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} old`
  const days = Math.round(hours / 24)
  return `${days} ${days === 1 ? "day" : "days"} old`
}

function citationFragment(n: number): string {
  if (n <= 0) return "no reports cited"
  if (n === 1) return "1 report cited"
  return `${n} reports cited`
}

/**
 * L-08 sentence pattern (CONTEXT.md):
 *   "{species} pin: {score_band} confidence, {age_human} old, {citation_count} reports cited"
 *
 * The {score_band} slot uses BAND_TO_LABEL ("High" | "Moderate" | "Low" | "unknown");
 * unknown collapses to "unknown confidence" per A11Y graceful fallback.
 */
export function buildAriaPinLabel(input: AriaPinInput): string {
  const speciesLabel = capitalize(input.species ?? "unknown")
  const band = scoreBand(input.score)
  const bandLabel = BAND_TO_LABEL[band]
  const confidencePhrase = band === "unknown" ? "unknown confidence" : `${bandLabel} confidence`
  return `${speciesLabel} pin: ${confidencePhrase}, ${humanAge(input.dataAgeSeconds)}, ${citationFragment(input.citationCount)}`
}
