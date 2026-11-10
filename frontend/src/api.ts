import type { ChatRequest, ChatResponse, StreamEvent } from "./types";

export interface HealthResponse {
  status: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch("/health");
  if (!res.ok) {
    throw new Error(`GET /health failed: ${res.status}`);
  }
  return (await res.json()) as HealthResponse;
}

/** POST /chat with stream:true and consume the text/event-stream response. */
export async function streamChat(
  request: ChatRequest,
  onProgress: (message: string) => void,
): Promise<ChatResponse> {
  const res = await fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    throw new Error(await errorDetail(res));
  }
  if (!res.body) {
    throw new Error("后端返回了空响应体");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let result: ChatResponse | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const event = parseSseEvent(chunk);
      if (!event) continue;
      if (event.event === "progress") {
        onProgress(event.message);
      } else if (event.event === "error") {
        throw new Error(event.message);
      } else if (event.event === "done") {
        result = toChatResponse(event);
      }
    }
  }

  const tail = parseSseEvent(buffer);
  if (tail && tail.event === "done") {
    result = toChatResponse(tail);
  }

  if (!result) {
    throw new Error("流式响应结束，但未收到 done 事件");
  }
  return result;
}

function toChatResponse(
  event: Extract<StreamEvent, { event: "done" }>,
): ChatResponse {
  return {
    reply: event.reply,
    plan: event.plan,
    question: event.question,
    done: event.done,
    messages: event.messages,
  };
}

function parseSseEvent(chunk: string): StreamEvent | null {
  let data = "";
  for (const line of chunk.split("\n")) {
    if (line.startsWith("data:")) {
      data += line.slice("data:".length).trim();
    }
  }
  if (!data) return null;
  try {
    return JSON.parse(data) as StreamEvent;
  } catch {
    return null;
  }
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // non-JSON error body; fall through to the generic message
  }
  return `HTTP ${res.status}`;
}
