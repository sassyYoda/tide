import { test } from "vitest"
import { execSync } from "node:child_process"

test.skipIf(!process.env.BACKEND_LIVE)(
  "api-types.ts matches live backend openapi.json",
  () => {
    execSync("pnpm gen:api-types:check", { stdio: "inherit" })
  },
)
