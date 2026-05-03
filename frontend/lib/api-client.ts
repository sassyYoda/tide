const API_URL = process.env.NEXT_PUBLIC_API_URL

if (!API_URL && typeof window !== "undefined") {
  // eslint-disable-next-line no-console
  console.warn("NEXT_PUBLIC_API_URL is not set; frontend will fail at runtime.")
}

export const apiUrl = (path: string): string => {
  if (!API_URL) {
    throw new Error("NEXT_PUBLIC_API_URL is not set")
  }
  return `${API_URL}${path.startsWith("/") ? path : `/${path}`}`
}
