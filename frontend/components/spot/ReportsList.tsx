"use client"
import type { CitationOut } from "@/lib/api-types"

interface Props {
  reports: CitationOut[] // NOTE: array (possibly empty), NOT optional
}

export function ReportsList({ reports }: Props) {
  // F-16 honest empty: array is empty when URL carried no `cite` param.
  // Do NOT render `<ol></ol>`. Render an honest stub.
  if (reports.length === 0) {
    return (
      <section
        data-testid="reports-empty"
        className="rounded-md border border-stone-300 bg-stone-50 p-3 text-sm text-stone-600"
      >
        <p className="font-medium">No cited reports for this view.</p>
        <p className="mt-1 text-xs">
          Reports flow into this page from the recommendation that linked
          you here.
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="reports-list"
      className="rounded-md border border-stone-200 bg-white p-3"
    >
      <h3 className="font-display text-sm uppercase tracking-wide text-stone-700">
        Cited reports
      </h3>
      <ol className="mt-2 space-y-2">
        {reports.map((c, i) => (
          <li
            key={`${c.source}-${i}`}
            className="rounded border border-stone-200 bg-stone-50 p-2 text-sm"
            data-testid="report-item"
          >
            {/* P11: render source/date as React text nodes only — no raw HTML insertion */}
            <div className="font-medium text-stone-900">{c.source}</div>
            {c.date && <div className="text-xs text-stone-500">{c.date}</div>}
          </li>
        ))}
      </ol>
    </section>
  )
}
