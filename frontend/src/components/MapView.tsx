import { useEffect, useRef } from "react";
import {
  LngLatBounds,
  Map as MaplibreMap,
  Marker,
  NavigationControl,
  Popup,
} from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import type { Plan, Stage } from "../types";
import { pointLabel, stageLine } from "../geometry";

const COLORS = ["#4fd1c5", "#f6ad55", "#7f9cf5"];
const FINAL_COLOR = "#ff6b6b";

const STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

export default function MapView({ plan }: { plan: Plan | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const stageIdsRef = useRef<string[]>([]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new MaplibreMap({
      container: containerRef.current,
      style: STYLE,
      center: [7.7, 50.4],
      zoom: 7.6,
    });
    map.addControl(new NavigationControl(), "top-right");
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const draw = () => {
      clearStages(map);
      if (plan) renderPlan(map, plan);
    };
    // The map is created in the effect above; plan is always null on first
    // render, but guard anyway so addSource/addLayer never race style load.
    if (map.loaded()) {
      draw();
    } else {
      map.once("load", draw);
    }
  }, [plan]);

  function clearStages(map: MaplibreMap) {
    for (const marker of markersRef.current) marker.remove();
    markersRef.current = [];
    for (const id of stageIdsRef.current) {
      if (map.getLayer(`stage-line-${id}`)) map.removeLayer(`stage-line-${id}`);
      if (map.getSource(`stage-source-${id}`)) {
        map.removeSource(`stage-source-${id}`);
      }
    }
    stageIdsRef.current = [];
  }

  function renderPlan(map: MaplibreMap, p: Plan) {
    const bounds = new LngLatBounds();
    p.stages.forEach((stage, i) => {
      const color = COLORS[i % COLORS.length];
      const id = String(stage.day);
      const line = stageLine(stage);

      map.addSource(`stage-source-${id}`, {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: line },
        },
      });
      map.addLayer({
        id: `stage-line-${id}`,
        type: "line",
        source: `stage-source-${id}`,
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": color, "line-width": 4 },
      });
      stageIdsRef.current.push(id);

      for (const coord of line) bounds.extend(coord);

      addMarker(
        map,
        stage.start,
        color,
        `Day ${stage.day} 起点 ${pointLabel(stage.start)}`,
      );
      const isLast = i === p.stages.length - 1;
      addMarker(
        map,
        stage.end,
        isLast ? FINAL_COLOR : color,
        `${isLast ? "终点" : `Day ${stage.day} 终点`} ${pointLabel(stage.end)}`,
      );
    });

    if (!bounds.isEmpty()) {
      const fit = () => map.fitBounds(bounds, { padding: 60, maxZoom: 12 });
      if (map.loaded()) fit();
      else map.once("load", fit);
    }
  }

  function addMarker(
    map: MaplibreMap,
    point: Stage["start"],
    color: string,
    label: string,
  ) {
    const marker = new Marker({ color })
      .setLngLat([point.lon, point.lat])
      .setPopup(new Popup().setText(label))
      .addTo(map);
    markersRef.current.push(marker);
  }

  return <div className="map" ref={containerRef} />;
}
