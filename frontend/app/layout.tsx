import type { Metadata, Viewport } from "next"
import { Inter, Bricolage_Grotesque } from "next/font/google"
import "./globals.css"
import { OfflineBanner } from "@/components/pwa/OfflineBanner"
import { InstallPromptIOS } from "@/components/pwa/InstallPromptIOS"

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
  adjustFontFallback: true,
})

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-bricolage",
  display: "swap",
  adjustFontFallback: true,
})

export const metadata: Metadata = {
  title: "Tide — Hyper-Local Fishing Intel",
  description: "NJ saltwater fishing recommendations powered by ML + LangGraph + RAG.",
  manifest: "/manifest.webmanifest",
  // P9 / A7 — appleWebApp.capable enables iOS A2HS; without this iOS falls
  // back to a screenshot-icon install which kills demo polish.
  appleWebApp: {
    capable: true,
    title: "Tide",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    // P9 MANDATORY — without this, iOS A2HS falls back to a page screenshot.
    apple: "/icons/apple-touch-icon-180.png",
  },
}

export const viewport: Viewport = {
  themeColor: "#0F766E",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${bricolage.variable}`}>
      <head>
        {/* Legacy iOS A2HS hint — A7 mitigation per RESEARCH Q8.
            Belt-and-suspenders: Next 16's appleWebApp metadata emits the same
            tags, but explicit literals cover Safari versions where the
            metadata API output drifts. */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-title" content="Tide" />
      </head>
      <body className="font-sans antialiased min-h-screen bg-tide-surface text-stone-900">
        <OfflineBanner />
        <InstallPromptIOS />
        {children}
      </body>
    </html>
  )
}
