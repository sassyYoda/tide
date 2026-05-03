import { describe, expect, test, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { ConfidenceBadge } from "@/components/query/ConfidenceBadge"

describe("ConfidenceBadge — L-11 + A8 fallback", () => {
  test.each([
    ["High", "High", "bg-tide-high"],
    ["Moderate", "Mod", "bg-tide-mid"],
    ["Low", "Low", "bg-tide-low"],
  ] as const)("label %s renders %s with %s class", (label, expected, klass) => {
    render(<ConfidenceBadge label={label} />)
    const badge = screen.getByTestId("confidence-badge")
    expect(badge.textContent).toBe(expected)
    expect(badge.className).toContain(klass)
  })

  test("A8 fallback: unexpected label → 'Unknown' + console warning + no crash", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {})
    render(<ConfidenceBadge label={"Bogus" as unknown as "High"} />)
    expect(screen.getByTestId("confidence-badge").textContent).toBe("Unknown")
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  test("tooltip explains the L-11 heuristic", () => {
    render(<ConfidenceBadge label="High" />)
    const badge = screen.getByTestId("confidence-badge")
    expect(badge.getAttribute("title")).toMatch(/3 recent reports/i)
  })
})
