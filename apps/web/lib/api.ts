import type {
  AuditCollection,
  AuditReport,
  Role,
  StreamHandlers,
  Thread,
  ThreadDetail,
  TraceGraph,
} from "./types";

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "gg_token";
const EMAIL_KEY = "gg_email";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getEmail(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(EMAIL_KEY);
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(EMAIL_KEY);
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function signIn(email: string, role: Role): Promise<void> {
  const { token } = await request<{ token: string }>("/auth/dev-token", {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(EMAIL_KEY, email);
}

export function listThreads(): Promise<Thread[]> {
  return request<Thread[]>("/threads");
}

export function createThread(title = ""): Promise<Thread> {
  return request<Thread>("/threads", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function getThread(threadId: string): Promise<ThreadDetail> {
  return request<ThreadDetail>(`/threads/${threadId}`);
}

export function deleteThread(threadId: string): Promise<void> {
  return request<void>(`/threads/${threadId}`, { method: "DELETE" });
}

export function listAuditCollections(): Promise<AuditCollection[]> {
  return request<AuditCollection[]>("/audit/collections");
}

export function runAuditReport(collectionId?: string): Promise<AuditReport> {
  const query = collectionId
    ? `?collection=${encodeURIComponent(collectionId)}`
    : "";
  return request<AuditReport>(`/audit/report${query}`);
}

export function getTrace(anchor: string, hops = 2): Promise<TraceGraph> {
  const query = `?anchor=${encodeURIComponent(anchor)}&hops=${hops}`;
  return request<TraceGraph>(`/graph/trace${query}`);
}

/** POST the question and consume the SSE stream. EventSource cannot POST,
 * so the stream is read from fetch's body and parsed manually. */
export async function streamMessage(
  threadId: string,
  content: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_URL}/threads/${threadId}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, "chat request failed");
  }
  await parseSseStream(response.body, handlers);
}

async function parseSseStream(
  body: ReadableStream<Uint8Array>,
  handlers: StreamHandlers,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "";
  let dataLines: string[] = [];

  const dispatch = () => {
    if (!eventName) return;
    const raw = dataLines.join("\n");
    let payload: unknown = {};
    try {
      payload = raw ? JSON.parse(raw) : {};
    } catch {
      payload = {};
    }
    routeEvent(eventName, payload, handlers);
    eventName = "";
    dataLines = [];
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex).replace(/\r$/, "");
      buffer = buffer.slice(newlineIndex + 1);
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      } else if (line === "") {
        dispatch();
      }
      newlineIndex = buffer.indexOf("\n");
    }
  }
  dispatch();
}

function routeEvent(
  name: string,
  payload: unknown,
  handlers: StreamHandlers,
): void {
  const data = (payload ?? {}) as Record<string, unknown>;
  switch (name) {
    case "step":
      handlers.onStep(data as { event: string });
      break;
    case "citations":
      handlers.onCitations(
        Array.isArray(data.items) ? (data.items as never[]) : [],
      );
      break;
    case "delta":
      handlers.onDelta(typeof data.text === "string" ? data.text : "");
      break;
    case "done":
      handlers.onDone({
        message_id: String(data.message_id ?? ""),
        verdict: typeof data.verdict === "string" ? data.verdict : null,
      });
      break;
    case "error":
      handlers.onError(
        typeof data.detail === "string" ? data.detail : "stream failed",
      );
      break;
    default:
      break;
  }
}
