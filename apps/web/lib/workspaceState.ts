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
