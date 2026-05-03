import { TideMap } from "@/components/map/TideMap"

export default function MapPage() {
  return (
    <main className="px-4 py-6">
      <h1 className="font-display text-3xl text-tide-high">Map</h1>
      <p className="mb-4 text-stone-700">Score-colored pins for NJ saltwater fishing spots.</p>
      <TideMap />
    </main>
  )
}
