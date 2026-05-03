"use client"
import { useCallback, useEffect, useRef, useState } from "react"
import Map, { type MapRef } from "react-map-gl/maplibre"
import maplibregl from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { apiUrl } from "@/lib/api-client"
import type { components } from "@/lib/api-types"
import { SpotPinLayer } from "./SpotPinLayer"
import { SpeciesFilter, type Species } from "./SpeciesFilter"
import { PinTooltip } from "./PinTooltip"
import { MapErrorToast } from "./MapErrorToast"

type SpotScore = components["schemas"]["SpotScore"]

const STYLE_URL =
  process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? "https://tiles.openfreemap.org/styles/liberty"
const ALL_SPECIES: Species[] = ["striper", "fluke", "bluefish", "weakfish", "tautog"]
const INITIAL_VIEW = { longitude: -74.1, latitude: 39.85, zoom: 9 } // Barnegat Bay

export function TideMap() {
  const mapRef = useRef<MapRef>(null)
  const [spots, setSpots] = useState<SpotScore[]>([])
  const [selectedSpecies, setSelectedSpecies] = useState<Species[]>([...ALL_SPECIES])
  const [tileError, setTileError] = useState<string | null>(null)
  const [hovered, setHovered] = useState<{ spot: SpotScore; x: number; y: number } | null>(null)

  // Fetch all spots in viewport bbox once on map idle.
  // F-04: species filter is client-side; do NOT include `species` query param.
  const fetchSpots = useCallback(async () => {
    const m = mapRef.current
    if (!m) return
    const b = m.getBounds()
    const bbox = `${b.getSouth()},${b.getWest()},${b.getNorth()},${b.getEast()}`
    try {
      const r = await fetch(apiUrl(`/api/v1/spots?bbox=${bbox}`))
      if (!r.ok) {
        // eslint-disable-next-line no-console
        console.warn("spots fetch failed", r.status)
        return
      }
      const data: SpotScore[] = await r.json()
      setSpots(data)
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("spots fetch error", err)
    }
  }, [])

  // Map error listener (RESEARCH Q1) — bind once map is ready.
  useEffect(() => {
    const m = mapRef.current?.getMap()
    if (!m) return
    const onErr = (e: { error?: { message?: string } }) => {
      const msg = e.error?.message ?? "tile load failure"
      if (/tile|sprite|glyph/i.test(msg)) {
        setTileError("Map tiles unavailable — pins still work")
      }
    }
    m.on("error", onErr)
    return () => {
      m.off("error", onErr)
    }
  }, [spots])

  return (
    <div className="relative h-[80vh] w-full">
      <SpeciesFilter all={ALL_SPECIES} selected={selectedSpecies} onChange={setSelectedSpecies} />
      <Map
        ref={mapRef}
        mapLib={maplibregl}
        initialViewState={INITIAL_VIEW}
        mapStyle={STYLE_URL}
        onLoad={fetchSpots}
        onMoveEnd={fetchSpots}
        attributionControl={{}}
        style={{ width: "100%", height: "100%" }}
      >
        <SpotPinLayer
          spots={spots}
          selectedSpecies={selectedSpecies}
          onPinHover={setHovered}
        />
      </Map>
      {hovered && <PinTooltip spot={hovered.spot} x={hovered.x} y={hovered.y} />}
      {tileError && (
        <MapErrorToast message={tileError} onDismiss={() => setTileError(null)} />
      )}
    </div>
  )
}
