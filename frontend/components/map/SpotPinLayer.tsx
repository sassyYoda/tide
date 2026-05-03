"use client"
import { useEffect, useMemo } from "react"
import { Layer, Source, useMap } from "react-map-gl/maplibre"
import type { FilterSpecification } from "maplibre-gl"
import type { components } from "@/lib/api-types"
import { scoreBand, type ScoreBand } from "@/lib/score-band"

type SpotScore = components["schemas"]["SpotScore"]

interface Props {
  spots: SpotScore[]
  selectedSpecies: string[]
  onPinHover: (h: { spot: SpotScore; x: number; y: number } | null) => void
}

const PIN_IMAGES: Record<Exclude<ScoreBand, "unknown">, string> = {
  high: "/pins/circle.svg",
  mid: "/pins/square.svg",
  low: "/pins/triangle.svg",
}

export function SpotPinLayer({ spots, selectedSpecies, onPinHover }: Props) {
  const { current: map } = useMap()

  // Load 3 SVG sprites into the map's image registry once. We attach the icon
  // under id `pin-{band}` to match the SymbolLayer `icon-image` declarations.
  useEffect(() => {
    if (!map) return
    const m = map.getMap()
    Object.entries(PIN_IMAGES).forEach(([band, src]) => {
      const imageId = `pin-${band}`
      if (m.hasImage(imageId)) return
      const img = new Image(24, 24)
      img.onload = () => {
        if (!m.hasImage(imageId)) m.addImage(imageId, img, { sdf: false })
      }
      img.src = src
    })
  }, [map])

  // Filter spots client-side by species (F-04 — no refetch).
  const filtered = useMemo(
    () =>
      spots.filter(
        (s) => s.species != null && selectedSpecies.includes(s.species) && s.score != null,
      ),
    [spots, selectedSpecies],
  )

  // Build a GeoJSON FeatureCollection — band as a property keys the 3 SymbolLayers.
  const fc = useMemo(
    () =>
      ({
        type: "FeatureCollection" as const,
        features: filtered.map((s) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [s.lon, s.lat] },
          properties: {
            spot_id: s.spot_id,
            name: s.name,
            species: s.species,
            score: s.score,
            band: scoreBand(s.score),
            data_age_seconds: s.data_age_seconds,
          },
        })),
      }) as GeoJSON.FeatureCollection,
    [filtered],
  )

  // Hover handler — parent shows tooltip.
  useEffect(() => {
    if (!map) return
    const m = map.getMap()
    const onMove = (e: maplibregl.MapMouseEvent) => {
      const features = m.queryRenderedFeatures(e.point, {
        layers: ["pins-high", "pins-mid", "pins-low"],
      })
      if (features.length > 0 && features[0]) {
        const props = features[0].properties as unknown as SpotScore
        onPinHover({ spot: props, x: e.point.x, y: e.point.y })
      } else {
        onPinHover(null)
      }
    }
    const onLeave = () => onPinHover(null)
    m.on("mousemove", onMove)
    m.on("mouseleave", onLeave)
    return () => {
      m.off("mousemove", onMove)
      m.off("mouseleave", onLeave)
    }
  }, [map, onPinHover])

  return (
    <Source
      id="spots"
      type="geojson"
      data={fc}
      cluster={true}
      clusterMaxZoom={9} // L-07: cluster < zoom 10, expand >= 10
      clusterRadius={40}
    >
      {/* Cluster bubble (single CircleLayer; clusters are not score-color-coded) */}
      <Layer
        id="spot-clusters"
        type="circle"
        filter={["has", "point_count"] as FilterSpecification}
        paint={{
          "circle-color": "#0F766E",
          "circle-radius": ["step", ["get", "point_count"], 16, 10, 22, 50, 28],
          "circle-opacity": 0.85,
        }}
      />
      <Layer
        id="cluster-count"
        type="symbol"
        filter={["has", "point_count"] as FilterSpecification}
        layout={{
          "text-field": ["get", "point_count_abbreviated"],
          "text-size": 12,
          "text-font": ["Open Sans Bold"],
        }}
        paint={{ "text-color": "#FAF8F1" }}
      />
      {/* Three SymbolLayers — one per band (P3: not radius-only). */}
      <Layer
        id="pins-high"
        type="symbol"
        filter={
          [
            "all",
            ["!", ["has", "point_count"]],
            ["==", ["get", "band"], "high"],
          ] as FilterSpecification
        }
        layout={{ "icon-image": "pin-high", "icon-size": 1.0, "icon-allow-overlap": true }}
      />
      <Layer
        id="pins-mid"
        type="symbol"
        filter={
          [
            "all",
            ["!", ["has", "point_count"]],
            ["==", ["get", "band"], "mid"],
          ] as FilterSpecification
        }
        layout={{ "icon-image": "pin-mid", "icon-size": 1.0, "icon-allow-overlap": true }}
      />
      <Layer
        id="pins-low"
        type="symbol"
        filter={
          [
            "all",
            ["!", ["has", "point_count"]],
            ["==", ["get", "band"], "low"],
          ] as FilterSpecification
        }
        layout={{ "icon-image": "pin-low", "icon-size": 1.0, "icon-allow-overlap": true }}
      />
    </Source>
  )
}
