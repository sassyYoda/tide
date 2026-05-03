"use client"
import { useState, type FormEvent } from "react"
import { Card } from "@/components/ui/card"
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"

interface Props {
  onSubmit: (query: string) => void
  disabled?: boolean
}

function InputForm({ onSubmit, disabled, autoFocus }: Props & { autoFocus?: boolean }) {
  const [value, setValue] = useState("")
  const remaining = 500 - value.length
  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setValue("")
  }
  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2" data-testid="query-form">
      <label htmlFor="tide-query" className="text-sm font-medium text-stone-700">
        Ask a fishing question
      </label>
      <textarea
        id="tide-query"
        data-testid="query-input"
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        maxLength={500}
        rows={3}
        placeholder="stripers at barnegat saturday morning"
        className="w-full resize-none rounded-md border border-stone-300 bg-white p-3 text-base text-stone-900 placeholder:text-stone-400 focus:border-tide-high focus:outline-none focus:ring-2 focus:ring-tide-high/40"
        disabled={disabled}
      />
      <div className="flex items-center justify-between">
        <span className={`text-xs ${remaining < 50 ? "text-tide-low" : "text-stone-500"}`}>
          {remaining} characters left
        </span>
        <Button
          type="submit"
          disabled={disabled || value.trim().length === 0}
          data-testid="query-submit"
          className="bg-tide-high text-white hover:bg-tide-high/90"
        >
          Ask Tide
        </Button>
      </div>
    </form>
  )
}

export function QueryInput(props: Props) {
  return (
    <>
      {/* Desktop: Card side panel (md+ visible) — L-09 */}
      <div className="hidden md:block" data-testid="query-input-desktop">
        <Card className="p-4">
          <InputForm {...props} autoFocus />
        </Card>
      </div>

      {/* Mobile: bottom Sheet (md hidden) — L-09 / F-13 */}
      <div className="md:hidden" data-testid="query-input-mobile">
        <Sheet>
          <SheetTrigger
            className="fixed bottom-4 left-4 right-4 z-20 inline-flex h-12 items-center justify-center rounded-md bg-tide-high px-6 text-base font-medium text-white shadow-lg hover:opacity-90"
            data-testid="query-sheet-trigger"
          >
            Ask Tide
          </SheetTrigger>
          <SheetContent side="bottom" className="rounded-t-2xl bg-tide-surface p-4">
            <InputForm {...props} autoFocus />
          </SheetContent>
        </Sheet>
      </div>
    </>
  )
}
