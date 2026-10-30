import type { Citation, Message, TraceEvent } from "./types";

/** An answer being streamed. threadId and requestId identify the request, so
 * callbacks from a request the user has moved away from never touch the view
 * of another thread. */
export interface LiveTurn {
  threadId: string;
  requestId: number;
  steps: TraceEvent[];
  draft: string;
  citations: Citation[];
}

/** A clicked [n] marker, tied to the message it appears in. */
export interface CitationSelection {
  messageId: string;
  marker: number;
}

export function liveTurnForThread(
  liveTurn: LiveTurn | null,
  threadId: string | null,
): LiveTurn | null {
  return liveTurn && liveTurn.threadId === threadId ? liveTurn : null;
}

/** Sources for the citation panel: the clicked message's citations, else the
 * live turn's, else the latest assistant message's. */
export function panelCitations(
  messages: Message[],
  liveTurn: LiveTurn | null,
  selection: CitationSelection | null,
): Citation[] {
  if (selection) {
    const selected = messages.find(
      (message) => message.id === selection.messageId,
    );
    if (selected) return selected.citations;
  }
  if (liveTurn?.citations.length) return liveTurn.citations;
  const lastAssistant = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");
  return lastAssistant?.citations ?? [];
}

/** The messages on screen and the thread they belong to. Messages are
 * replaced the moment another thread opens, so one thread's history is never
 * shown under another, and sending waits until the history has loaded. */
export interface ThreadView {
  threadId: string | null;
  status: "loading" | "ready" | "failed";
  messages: Message[];
}

export function emptyThreadView(): ThreadView {
  return { threadId: null, status: "ready", messages: [] };
}

export function openingThread(threadId: string): ThreadView {
  return { threadId, status: "loading", messages: [] };
}

/** Apply a history response; one for a thread no longer shown is ignored. */
export function threadLoaded(
  view: ThreadView,
  threadId: string,
  messages: Message[],
): ThreadView {
  return view.threadId === threadId
    ? { threadId, status: "ready", messages }
    : view;
}

export function threadLoadFailed(
  view: ThreadView,
  threadId: string,
): ThreadView {
  return view.threadId === threadId ? { ...view, status: "failed" } : view;
}

export function canSend(view: ThreadView, turnStreaming: boolean): boolean {
  return view.status === "ready" && !turnStreaming;
}
