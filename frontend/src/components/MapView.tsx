import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { BasinFeature, Site } from "../lib/data";
import { RISK_COLORS, NO_DATA_COLOR, riskColor } from "../lib/risk";

const STYLES: Record<string, string | maplibregl.StyleSpecification> = {
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  sat: {
    version: 8,
    sources: {
      esri: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        attribution: "Esri, Maxar, Earthstar Geographics",
      },
    },
    layers: [{ id: "esri", type: "raster", source: "esri" }],
  },
};

interface Props {
  basins: BasinFeature[];
  sites: Site[];
  siteOverall: Record<string, number | null>; // site id -> overall score (for pin color)
  layerProp: string; // normalized prop the choropleth reads
  basemap: "dark" | "light" | "sat";
  flyTo: { lat: number; lng: number } | null;
  subbasins: any | null;                      // level-9 FeatureCollection or null
  pickMode: boolean;                          // add-site: next click sets coordinates
  onPick: (lat: number, lng: number) => void;
  onSelect: (site: Site) => void;
}

const EMPTY_FC = { type: "FeatureCollection", features: [] } as any;

export default function MapView({ basins, sites, siteOverall, layerProp, basemap, flyTo, subbasins, pickMode, onPick, onSelect }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const pickRef = useRef(pickMode);
  const onPickRef = useRef(onPick);
  const subsRef = useRef<any | null>(subbasins); // survives basemap style swaps
  pickRef.current = pickMode;
  onPickRef.current = onPick;
  subsRef.current = subbasins;

  const fc = (): GeoJSON.FeatureCollection => ({
    type: "FeatureCollection",
    features: basins.map((b) => ({
      ...b,
      properties: { ...b.properties, __val: b.properties[layerProp] ?? null },
    })) as any,
  });

  const addLayers = (map: maplibregl.Map) => {
    if (map.getSource("basins")) return;
    map.addSource("basins", { type: "geojson", data: fc() });
    map.addLayer({
      id: "basin-fill",
      type: "fill",
      source: "basins",
      paint: {
        "fill-color": [
          "case",
          ["==", ["typeof", ["get", "__val"]], "number"],
          ["step", ["get", "__val"], RISK_COLORS[0], 1, RISK_COLORS[1], 2, RISK_COLORS[2], 3, RISK_COLORS[3], 4, RISK_COLORS[4]],
          NO_DATA_COLOR,
        ] as any,
        "fill-opacity": 0.55,
      },
    });
    map.addLayer({
      id: "basin-line",
      type: "line",
      source: "basins",
      paint: { "line-color": "rgba(255,255,255,0.25)", "line-width": 1 },
    });
    // relief ring for Extremely High (#BD0026 is <3:1 on the dark surface)
    map.addLayer({
      id: "basin-line-extreme",
      type: "line",
      source: "basins",
      filter: [">=", ["get", "__val"], 4] as any,
      paint: { "line-color": "rgba(255,255,255,0.65)", "line-width": 2 },
    });
    // finer level-9 sub-basins around the selected site (drawn above the coarse basin);
    // seeded from the ref so a basemap switch doesn't wipe the overlay
    map.addSource("subs", { type: "geojson", data: subsRef.current ?? EMPTY_FC });
    map.addLayer({
      id: "subs-fill",
      type: "fill",
      source: "subs",
      paint: {
        "fill-color": [
          "case",
          ["==", ["typeof", ["get", "overall"]], "number"],
          ["step", ["get", "overall"], RISK_COLORS[0], 1, RISK_COLORS[1], 2, RISK_COLORS[2], 3, RISK_COLORS[3], 4, RISK_COLORS[4]],
          NO_DATA_COLOR,
        ] as any,
        "fill-opacity": 0.4,
      },
    });
    map.addLayer({
      id: "subs-line",
      type: "line",
      source: "subs",
      paint: { "line-color": "rgba(255,255,255,0.45)", "line-width": 0.8 },
    });
  };

  // init once
  useEffect(() => {
    if (!el.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: el.current,
      style: STYLES.dark as any,
      center: [40, 22],
      zoom: 2.2,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    map.on("load", () => addLayers(map));
    map.on("click", (e) => {
      if (pickRef.current) onPickRef.current(e.lngLat.lat, e.lngLat.lng);
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // basemap switch: setStyle wipes layers -> re-add once the new style is fully
  // loaded ("idle" guarantees it; a styledata+timeout race can throw mid-load)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(STYLES[basemap] as any);
    map.once("idle", () => addLayers(map));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap]);

  // choropleth data (layer switch or basins load)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const src = map.getSource("basins") as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(fc() as any);
      else addLayers(map);
    };
    // "idle" (not "load") — load fires only once ever, so it would drop updates
    // that arrive while a basemap style swap is still in flight
    if (map.isStyleLoaded()) apply();
    else map.once("idle", apply);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basins, layerProp]);

  // site pins
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = sites.map((s) => {
      const overall = siteOverall[s.id] ?? null;
      const d = document.createElement("div");
      d.className = "site-pin";
      d.style.background = riskColor(overall);
      d.title = `${s.name} — overall ${overall ?? "no data"}`;
      d.onclick = (e) => { e.stopPropagation(); onSelect(s); };
      return new maplibregl.Marker({ element: d }).setLngLat([s.lng, s.lat]).addTo(map);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sites, siteOverall]);

  useEffect(() => {
    if (flyTo && mapRef.current) mapRef.current.flyTo({ center: [flyTo.lng, flyTo.lat], zoom: 8 });
  }, [flyTo]);

  // sub-basins overlay
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      const src = map.getSource("subs") as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(subbasins ?? EMPTY_FC);
    };
    if (map.isStyleLoaded()) apply();
    else map.once("idle", apply);
  }, [subbasins]);

  // crosshair cursor while picking coordinates
  useEffect(() => {
    const map = mapRef.current;
    if (map) map.getCanvas().style.cursor = pickMode ? "crosshair" : "";
  }, [pickMode]);

  return <div ref={el} style={{ position: "absolute", top: 56, left: 0, right: 0, bottom: 0 }} />;
}
