import type { Metadata, Viewport } from "next"
import { Inter, Bricolage_Grotesque } from "next/font/google"
import "./globals.css"

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
  appleWebApp: {
    capable: true,
    title: "Tide",
    statusBarStyle: "default",
  },
  icons: {
    icon: "/icons/favicon.ico",
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
        {/* Legacy iOS A2HS hint — A7 mitigation per RESEARCH Q8 */}
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-title" content="Tide" />
      </head>
      <body className="font-sans antialiased min-h-screen bg-tide-surface text-stone-900">
        {children}
      </body>
    </html>
  )
}
