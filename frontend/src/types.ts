// Types mirroring the FastAPI backend (rideflow/models.py) and the /chat
// response contract in rideflow/main.py.

export interface ChatMessage {
  id: number;
  role: "user" | "bot";
  text: string;
}

/** Opaque serialized LangChain message; passed straight back as history. */
export type SerializedMessage = Record<string, unknown>;

export interface Point {
  name: string;
  lon: number;
  lat: number;
}

export interface ParsedIntent {
  origin: string;
  destination: string;
  days: number;
  target_daily_km: number | null;
}

export interface Intent {
  raw: string;
  parsed: ParsedIntent;
}

export interface Route {
  geometry: string;
  distance_km: number;
  climb_m: number;
  descent_m: number;
  surface_breakdown: Record<string, number>;
}

export interface Stage {
  day: number;
  start: Point;
  end: Point;
  route: Route;
  via: Point[];
  poi_refs: string[];
  notes: string;
  status: string;
}

export interface Metadata {
  model: string;
  created_at: string;
  version: number;
}

export interface Plan {
  id: string;
  intent: Intent;
  stages: Stage[];
  metadata: Metadata;
}

export interface ChatResponse {
  reply: string;
  plan: Plan | null;
  question: string | null;
  done: boolean;
  messages: SerializedMessage[];
}

export interface ChatRequest {
  message: string;
  history: SerializedMessage[];
  stream: boolean;
}

export type StreamEvent =
  | { event: "progress"; message: string }
  | ({ event: "done" } & ChatResponse)
  | { event: "error"; message: string };
