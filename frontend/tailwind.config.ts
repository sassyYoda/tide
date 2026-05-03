import type { Config } from "tailwindcss"

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        tide: {
          high: "#0F766E",
          mid: "#EAB308",
          low: "#B91C1C",
          surface: "#FAF8F1",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-bricolage)", "Georgia", "serif"],
      },
    },
  },
  plugins: [],
} satisfies Config
