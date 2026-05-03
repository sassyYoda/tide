import type { NextConfig } from "next"
import withSerwistInit from "@serwist/next"

const withSerwist = withSerwistInit({
  swSrc: "app/sw.ts",
  swDest: "public/sw.js",
  cacheOnNavigation: true,
  reloadOnOnline: true,
  disable: process.env.NODE_ENV === "development",
})

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Empty turbopack stanza silences the "webpack config + no turbopack config"
  // error that Next 16 emits when @serwist/next injects its webpack plugin.
  // (Plan 07 may revisit if SW dev experience improves; for now SW is
  // production-only via `disable: NODE_ENV === 'development'`.)
  turbopack: {},
}

export default withSerwist(nextConfig)
