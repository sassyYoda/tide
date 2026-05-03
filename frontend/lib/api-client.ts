// Read on each call so tests using `vi.stubEnv("NEXT_PUBLIC_API_URL", ...)` work
// (env captured at module load doesn't see stubs registered later in beforeEach).
export const apiUrl = (path: string): string => {
  const base = process.env.NEXT_PUBLIC_API_URL
  if (!base) {
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.warn("NEXT_PUBLIC_API_URL is not set; frontend will fail at runtime.")
    }
    throw new Error("NEXT_PUBLIC_API_URL is not set")
  }
  return `${base}${path.startsWith("/") ? path : `/${path}`}`
}
