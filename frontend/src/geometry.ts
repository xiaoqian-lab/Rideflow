import type { Point, Stage } from "./types";

export type LngLatTuple = [number, number];

/** Human label for a point; interpolated midpoints have an empty name. */
export function pointLabel(point: Point): string {
  const name = point.name.trim();
  if (name) return name;
  return `${point.lon.toFixed(2)}, ${point.lat.toFixed(2)}`;
}

/**
 * Parse the backend's straight-line geometry format: a semicolon-separated
 * string of "lon,lat" pairs, e.g. "8.27,49.99;7.59,50.35". Returns an array of
 * [lon, lat] tuples suitable for a GeoJSON LineString.
 *
 * (Real Valhalla routes use a different encoded polyline format; this frontend
 * ticket only needs to handle the semicolon format plus the start/end fallback.)
 */
export function parseGeometry(
  geometry: string | null | undefined,
): LngLatTuple[] {
  if (!geometry) return [];
  const points: LngLatTuple[] = [];
  for (const part of geometry.split(";")) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const [lonPart, latPart] = trimmed.split(",");
    const lon = Number(lonPart);
    const lat = Number(latPart);
    if (Number.isFinite(lon) && Number.isFinite(lat)) {
      points.push([lon, lat]);
    }
  }
  return points;
}

/** Line for a stage: parsed geometry, or a straight start -> end fallback. */
export function stageLine(stage: Stage): LngLatTuple[] {
  const parsed = parseGeometry(stage.route?.geometry);
  if (parsed.length >= 2) return parsed;
  return [
    [stage.start.lon, stage.start.lat],
    [stage.end.lon, stage.end.lat],
  ];
}
