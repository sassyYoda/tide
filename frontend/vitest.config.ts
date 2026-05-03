import { defineConfig } from "vitest/config"
import path from "node:path"

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: true,
    css: false,
    include: ["tests/**/*.test.{ts,tsx}"],
    exclude: ["tests/**/*.spec.ts", "node_modules", ".next"],
  },
  resolve: { alias: { "@": path.resolve(__dirname, ".") } },
})
