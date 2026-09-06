import type { FullConfig } from "@playwright/test"

export default async function globalSetup(_config: FullConfig) {
  if (!process.env.BACKEND_LIVE) return
  const url = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${url}/api/v1/healthz`)
      if (r.ok) return
    } catch {
      /* ignore */
    }
    await new Promise((res) => setTimeout(res, 500))
  }
  throw new Error(`Backend at ${url}/api/v1/healthz did not become healthy in 30s`)
}
