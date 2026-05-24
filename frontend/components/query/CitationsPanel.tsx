"use client"
import { useState } from "react"
import type { CitationOut } from "@/lib/api-types"
import { Sheet, SheetContent, SheetTrigger, SheetTitle, SheetHeader } from "@/components/ui/sheet"
import { Dialog, DialogContent, DialogTrigger, DialogTitle, DialogHeader } from "@/components/ui/dialog"

interface Props {
  citations: CitationOut[]
}

function CitationList({ citations }: Props) {
  if (citations.length === 0) {
    return <p className="text-sm text-stone-500">No citations available.</p>
  }
  return (
    <ol className="space-y-3" data-testid="citations-list">
      {citations.map((c, i) => {
        // P11: render source/date as React text nodes only — never raw HTML insertion.
        // When source_url is present, wrap the source line in an external <a>;
        // otherwise fall back to a plain text node.
        const hasUrl = !!c.source_url
        const sourceContent = hasUrl ? (
          <a
            href={c.source_url as string}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-tide-high underline-offset-2 hover:underline"
            data-testid="citation-source-link"
          >
            {c.source}
            <span aria-hidden="true" className="ml-1 text-xs">
              ↗
            </span>
            <span className="sr-only"> (opens in new tab)</span>
          </a>
        ) : (
          <span className="font-medium text-stone-900">{c.source}</span>
        )
        return (
          <li
            key={`${c.source}-${i}`}
            className="rounded-md border border-stone-200 bg-white p-3 text-sm"
          >
            <div>{sourceContent}</div>
            {c.date && <div className="text-xs text-stone-500">{c.date}</div>}
            {c.chunk_id && (
              <div className="mt-1 font-mono text-xs text-stone-400">{c.chunk_id}</div>
            )}
          </li>
        )
      })}
    </ol>
  )
}

export function CitationsPanel({ citations }: Props) {
  const count = citations.length
  const triggerLabel = count === 1 ? "1 citation" : `${count} citations`

  // Two independent state flags so each variant manages its own open state.
  const [desktopOpen, setDesktopOpen] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  return (
    <>
      {/* Desktop: Sheet on the right (md+) — L-10 */}
      <div className="hidden md:inline-block" data-testid="citations-desktop">
        <Sheet open={desktopOpen} onOpenChange={setDesktopOpen}>
          {/* SheetTrigger renders its own <button> — apply Button styling via className. */}
          <SheetTrigger
            data-testid="citations-trigger-desktop"
            disabled={count === 0}
            className="inline-flex h-10 items-center justify-center rounded-md border border-stone-300 bg-transparent px-4 py-2 text-sm font-medium transition-colors hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-tide-high disabled:pointer-events-none disabled:opacity-50"
          >
            View {triggerLabel}
          </SheetTrigger>
          <SheetContent side="right" className="w-[420px] bg-white">
            <SheetHeader>
              <SheetTitle>Sources</SheetTitle>
            </SheetHeader>
            <div className="mt-4">
              <CitationList citations={citations} />
            </div>
          </SheetContent>
        </Sheet>
      </div>

      {/* Mobile: Dialog (md hidden) — L-10 */}
      <div className="inline-block md:hidden" data-testid="citations-mobile">
        <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
          <DialogTrigger
            data-testid="citations-trigger-mobile"
            disabled={count === 0}
            className="inline-flex h-10 items-center justify-center rounded-md border border-stone-300 bg-transparent px-4 py-2 text-sm font-medium transition-colors hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-tide-high disabled:pointer-events-none disabled:opacity-50"
          >
            View {triggerLabel}
          </DialogTrigger>
          <DialogContent className="max-h-[85vh] overflow-y-auto bg-white">
            <DialogHeader>
              <DialogTitle>Sources</DialogTitle>
            </DialogHeader>
            <div className="mt-4">
              <CitationList citations={citations} />
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </>
  )
}
