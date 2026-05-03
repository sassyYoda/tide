"use client"
import { useEffect } from "react"

interface Props {
  message: string
  onDismiss: () => void
}

export function MapErrorToast({ message, onDismiss }: Props) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 6000)
    return () => clearTimeout(t)
  }, [onDismiss])
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="map-error-toast"
      className="absolute bottom-4 left-1/2 z-30 -translate-x-1/2 rounded-md bg-stone-900/90 px-4 py-2 text-sm text-white shadow"
    >
      {message}
    </div>
  )
}
