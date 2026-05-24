import { describe, expect, test } from "vitest"
import { render, screen, within } from "@testing-library/react"
import { ReportsList } from "@/components/spot/ReportsList"
import type { CitationOut } from "@/lib/api-types"

describe("ReportsList — source_url linkification", () => {
  test("renders an external <a> when source_url is present", () => {
    const reports: CitationOut[] = [
      {
        source: "njfishing",
        date: "2026-05-22",
        chunk_id: "c1",
        source_url: "https://njfishing.com/forum/thread/9001",
      },
    ]
    render(<ReportsList reports={reports} />)

    const link = screen.getByTestId("report-source-link")
    expect(link.tagName).toBe("A")
    expect(link).toHaveAttribute("href", "https://njfishing.com/forum/thread/9001")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
    expect(link).toHaveTextContent("njfishing")
  })

  test("falls back to plain text when source_url is null", () => {
    const reports: CitationOut[] = [
      {
        source: "stripersonline",
        date: "2026-05-22",
        chunk_id: "c1",
        source_url: null,
      },
    ]
    render(<ReportsList reports={reports} />)

    expect(screen.queryByTestId("report-source-link")).toBeNull()
    const item = screen.getByTestId("report-item")
    expect(within(item).getByText("stripersonline")).toBeTruthy()
  })

  test("falls back to plain text when source_url is empty string", () => {
    const reports: CitationOut[] = [
      {
        source: "njfishing",
        date: "2026-05-22",
        chunk_id: "c1",
        source_url: "" as unknown as string,
      },
    ]
    render(<ReportsList reports={reports} />)

    expect(screen.queryByTestId("report-source-link")).toBeNull()
    const item = screen.getByTestId("report-item")
    expect(within(item).getByText("njfishing")).toBeTruthy()
  })

  test("renders honest empty-state when reports array is empty", () => {
    render(<ReportsList reports={[]} />)
    expect(screen.getByTestId("reports-empty")).toBeTruthy()
  })
})
