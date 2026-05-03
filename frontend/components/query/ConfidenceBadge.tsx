"use client"
import type { ConfidenceLabel } from "@/lib/api-types"

interface Props {
  label: ConfidenceLabel | string // accept string to allow A8 graceful fallback
}

const TOOLTIP =
  "How Tide grades recommendations: ≥3 recent reports + ML score → High; ≥2 recent reports → Moderate; otherwise Low."

export function ConfidenceBadge({ label }: Props) {
  let display: string
  let bgClass: string

  switch (label) {
    case "High":
      display = "High"
      bgClass = "bg-tide-high text-white"
      break
    case "Moderate":
      display = "Mod"
      bgClass = "bg-tide-mid text-stone-900"
      break
    case "Low":
      display = "Low"
      bgClass = "bg-tide-low text-white"
      break
    default:
      // A8 fallback — RESEARCH.md line 522-523. Do NOT crash on unexpected values.
      // eslint-disable-next-line no-console
      console.warn("[ConfidenceBadge] Unexpected confidence_label:", label)
      display = "Unknown"
      bgClass = "bg-stone-400 text-white"
  }

  return (
    <span
      role="status"
      aria-label={`Confidence: ${display}. ${TOOLTIP}`}
      title={TOOLTIP}
      data-testid="confidence-badge"
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${bgClass}`}
    >
      {display}
    </span>
  )
}
