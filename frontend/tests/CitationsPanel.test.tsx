import { describe, expect, test } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { CitationsPanel } from "@/components/query/CitationsPanel"
import type { CitationOut } from "@/lib/api-types"

// CitationsPanel renders both a desktop (Sheet) and a mobile (Dialog) variant.
// Triggers are visible until clicked; the CitationList only mounts in the
// portal once a variant is opened. To exercise the rendering branches in unit
// scope without simulating the open state, we render the inner list via the
// desktop variant and open it programmatically by toggling visibility through
// the trigger click is not necessary — Radix portals to document.body once
// the open state flips. The simplest, jsdom-friendly path is to test the
// branch behavior end-to-end via the trigger.
//
// However, for source_url branch coverage we only need to assert what the
// CitationList renders. We do that by mounting CitationsPanel and using
// the desktop trigger click to open the Sheet.
import { fireEvent } from "@testing-library/react"

function open(): void {
  // Click the desktop trigger to open the Sheet (Dialog is hidden via CSS in
  // jsdom but both triggers are mounted; we use the desktop one).
  const trigger = screen.getByTestId("citations-trigger-desktop")
  fireEvent.click(trigger)
}

describe("CitationsPanel — source_url linkification", () => {
  test("renders an external <a> when source_url is present", () => {
    const citations: CitationOut[] = [
      {
        source: "njfishing",
        date: "2026-05-22",
        chunk_id: "abc-123",
        source_url: "https://njfishing.com/forum/thread/9001",
      },
    ]
    render(<CitationsPanel citations={citations} />)
    open()

    const link = screen.getByTestId("citation-source-link")
    expect(link.tagName).toBe("A")
    expect(link).toHaveAttribute("href", "https://njfishing.com/forum/thread/9001")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
    expect(link).toHaveTextContent("njfishing")
  })

  test("falls back to plain text when source_url is null", () => {
    const citations: CitationOut[] = [
      {
        source: "stripersonline",
        date: "2026-05-22",
        chunk_id: "xyz-9",
        source_url: null,
      },
    ]
    render(<CitationsPanel citations={citations} />)
    open()

    expect(screen.queryByTestId("citation-source-link")).toBeNull()
    const list = screen.getByTestId("citations-list")
    expect(within(list).getByText("stripersonline")).toBeTruthy()
  })

  test("falls back to plain text when source_url is empty string", () => {
    const citations: CitationOut[] = [
      {
        source: "njfishing",
        date: "2026-05-22",
        chunk_id: "abc",
        source_url: "" as unknown as string,
      },
    ]
    render(<CitationsPanel citations={citations} />)
    open()

    expect(screen.queryByTestId("citation-source-link")).toBeNull()
    const list = screen.getByTestId("citations-list")
    expect(within(list).getByText("njfishing")).toBeTruthy()
  })
})
