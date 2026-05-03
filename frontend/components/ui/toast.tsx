"use client"

import * as React from "react"

export type ToastVariant = "default" | "destructive" | "success"

export interface Toast {
  id: string
  title?: string
  description?: string
  variant?: ToastVariant
}

type ToastContextValue = {
  toasts: Toast[]
  toast: (t: Omit<Toast, "id">) => void
  dismiss: (id: string) => void
}

const ToastContext = React.createContext<ToastContextValue | null>(null)

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([])

  const toast = React.useCallback((t: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).slice(2)
    setToasts((prev) => [...prev, { id, ...t }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id))
    }, 4000)
  }, [])

  const dismiss = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((x) => x.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={{ toasts, toast, dismiss }}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = React.useContext(ToastContext)
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider")
  }
  return ctx
}

const variantClasses: Record<ToastVariant, string> = {
  default: "border-stone-200 bg-white text-stone-900",
  destructive: "border-tide-low bg-tide-low text-white",
  success: "border-tide-high bg-tide-high text-white",
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[]
  onDismiss: (id: string) => void
}) {
  return (
    <div
      role="region"
      aria-label="Notifications"
      className="pointer-events-none fixed bottom-0 right-0 z-50 flex w-full flex-col gap-2 p-4 sm:max-w-sm"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`pointer-events-auto rounded-md border p-4 shadow-md ${
            variantClasses[t.variant ?? "default"]
          }`}
        >
          {t.title && <div className="font-medium">{t.title}</div>}
          {t.description && <div className="text-sm opacity-90">{t.description}</div>}
          <button
            type="button"
            className="mt-1 text-xs underline opacity-80"
            onClick={() => onDismiss(t.id)}
          >
            Dismiss
          </button>
        </div>
      ))}
    </div>
  )
}

export default ToastProvider
