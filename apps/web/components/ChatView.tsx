"use client";

import { useEffect, useRef, useState } from "react";
import type { Message } from "@/lib/types";
import type { LiveTurn } from "./Workspace";
import MessageBubble from "./MessageBubble";
import StepTrace from "./StepTrace";

export default function ChatView({
  messages,
  liveTurn,
  busy,
  error,
  onSend,
  onMarkerClick,
}: {
  messages: Message[];
  liveTurn: LiveTurn | null;
  // A turn is streaming somewhere, possibly in another thread.
  busy: boolean;
  error: string | null;
  onSend: (content: string) => void;
  onMarkerClick: (messageId: string, marker: number) => void;
}) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const streaming = liveTurn !== null || busy;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, liveTurn]);

  function submit() {
    const content = draft.trim();
    if (!content || streaming) return;
    setDraft("");
    onSend(content);
  }

  return (
    <main className="chat-col">
      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-inner">
          {messages.length === 0 && liveTurn === null ? (
            <div className="empty-state">
              <h2>Ask the quality system</h2>
              <p>
                Questions are answered only from ingested QMS documents, with
                citations. Try: &ldquo;What does the CAPA procedure require
                before a CAPA can be closed?&rdquo;
              </p>
            </div>
          ) : null}
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              onMarkerClick={(marker) => onMarkerClick(message.id, marker)}
            />
          ))}
          {liveTurn ? (
            <div className="message assistant">
              <StepTrace steps={liveTurn.steps} live />
              {liveTurn.draft ? (
                <div className="bubble">{liveTurn.draft}</div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      <div className="composer">
        <div className="composer-inner">
          <textarea
            value={draft}
            placeholder="Ask about SOPs, CAPAs, complaints, design history…"
            rows={1}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <button
            className="btn-primary"
            onClick={submit}
            disabled={streaming || !draft.trim()}
          >
            {streaming ? "Working…" : "Send"}
          </button>
        </div>
        <div className="composer-hint">
          Answers cite corpus documents; anything the corpus cannot support is
          flagged instead of guessed.
        </div>
      </div>
    </main>
  );
}
