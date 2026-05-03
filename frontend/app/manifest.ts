import type { MetadataRoute } from "next"

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Tide — Hyper-Local Fishing Intel",
    short_name: "Tide",
    description: "NJ saltwater fishing recommendations",
    start_url: "/",
    display: "standalone",
    background_color: "#FAF8F1",
    theme_color: "#0F766E",
    orientation: "any",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  }
}
