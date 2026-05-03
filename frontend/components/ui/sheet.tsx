"use client"

import * as React from "react"

type SheetContextValue = {
  open: boolean
  setOpen: (open: boolean) => void
}

const SheetContext = React.createContext<SheetContextValue | null>(null)

interface SheetProps {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  defaultOpen?: boolean
  children: React.ReactNode
}

const Sheet = ({ open: controlledOpen, onOpenChange, defaultOpen = false, children }: SheetProps) => {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen)
  const open = controlledOpen ?? uncontrolledOpen
  const setOpen = (next: boolean) => {
    if (controlledOpen === undefined) setUncontrolledOpen(next)
    onOpenChange?.(next)
  }
  return <SheetContext.Provider value={{ open, setOpen }}>{children}</SheetContext.Provider>
}

const SheetTrigger = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement>
>(({ onClick, ...props }, ref) => {
  const ctx = React.useContext(SheetContext)
  return (
    <button
      ref={ref}
      onClick={(e) => {
        ctx?.setOpen(true)
        onClick?.(e)
      }}
      {...props}
    />
  )
})
SheetTrigger.displayName = "SheetTrigger"

interface SheetContentProps extends React.HTMLAttributes<HTMLDivElement> {
  side?: "top" | "right" | "bottom" | "left"
}

const SheetContent = React.forwardRef<HTMLDivElement, SheetContentProps>(
  ({ className = "", side = "right", children, ...props }, ref) => {
    const ctx = React.useContext(SheetContext)
    if (!ctx?.open) return null
    const sideClasses: Record<NonNullable<SheetContentProps["side"]>, string> = {
      top: "inset-x-0 top-0 border-b",
      right: "inset-y-0 right-0 h-full w-3/4 border-l sm:max-w-sm",
      bottom: "inset-x-0 bottom-0 border-t",
      left: "inset-y-0 left-0 h-full w-3/4 border-r sm:max-w-sm",
    }
    return (
      <div className="fixed inset-0 z-50">
        <div
          className="fixed inset-0 bg-black/40"
          onClick={() => ctx.setOpen(false)}
          aria-hidden
        />
        <div
          ref={ref}
          role="dialog"
          aria-modal="true"
          className={`fixed bg-white p-6 shadow-lg ${sideClasses[side]} ${className}`}
          {...props}
        >
          {children}
        </div>
      </div>
    )
  },
)
SheetContent.displayName = "SheetContent"

const SheetHeader = ({ className = "", ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={`flex flex-col space-y-2 text-left ${className}`} {...props} />
)

const SheetTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className = "", ...props }, ref) => (
    <h2
      ref={ref}
      className={`font-display text-lg font-semibold text-stone-900 ${className}`}
      {...props}
    />
  ),
)
SheetTitle.displayName = "SheetTitle"

const SheetDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className = "", ...props }, ref) => (
  <p ref={ref} className={`text-sm text-stone-500 ${className}`} {...props} />
))
SheetDescription.displayName = "SheetDescription"

export { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription }
export default Sheet
