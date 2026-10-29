"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  clearSession,
  createThread,
  getThread,
  listThreads,
  streamMessage,
} from "@/lib/api";
import type { Citation, Message, Thread, TraceEvent } from "@/lib/types";
import AuditPanel from "./AuditPanel";
import ChatView from "./ChatView";
import CitationPanel from "./CitationPanel";
import ThreadSidebar, { type WorkspaceView } from "./ThreadSidebar";

export interface LiveTurn {
  steps: TraceEvent[];
  draft: string;
  citations: Citation[];
}

export default function Workspace({
  email,
  onSignOut,
}: {
  email: string;
  onSignOut: () => void;
}) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [view, setView] = useState<WorkspaceView>("chat");
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [liveTurn, setLiveTurn] = useState<LiveTurn | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlightMarker, setHighlightMarker] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const signOut = useCallback(() => {
    clearSession();
    onSignOut();
  }, [onSignOut]);

  const handleFailure = useCallback(
    (err: unknown, fallback: string) => {
      if (err instanceof ApiError && err.status === 401) {
        signOut();
        return;
      }
      setError(err instanceof ApiError ? err.message : fallback);
    },
    [signOut],
  );

  const refreshThreads = useCallback(async () => {
    try {
      setThreads(await listThreads());
    } catch (err) {
      handleFailure(err, "could not load threads");
    }
  }, [handleFailure]);

  useEffect(() => {
    void refreshThreads();
    return () => abortRef.current?.abort();
  }, [refreshThreads]);

  const openThread = useCallback(
    async (threadId: string) => {
      setView("chat");
      setActiveThreadId(threadId);
      setHighlightMarker(null);
      try {
        const detail = await getThread(threadId);
        setMessages(detail.messages);
      } catch (err) {
        handleFailure(err, "could not load the thread");
      }
    },
    [handleFailure],
  );

  const newThread = useCallback(() => {
    setView("chat");
    setActiveThreadId(null);
    setMessages([]);
    setHighlightMarker(null);
    setError(null);
  }, []);

  const send = useCallback(
    async (content: string) => {
      setError(null);
      setHighlightMarker(null);
      let threadId = activeThreadId;
      try {
        if (!threadId) {
          const thread = await createThread();
          threadId = thread.id;
          setActiveThreadId(threadId);
        }
      } catch (err) {
        handleFailure(err, "could not create a thread");
        return;
      }

      const userMessage: Message = {
        id: `local-${content.length}-${messages.length}`,
        role: "user",
        content,
        verdict: null,
        citations: [],
        trace: [],
        created_at: "",
      };
      setMessages((current) => [...current, userMessage]);
      setLiveTurn({ steps: [], draft: "", citations: [] });

      const controller = new AbortController();
      abortRef.current = controller;
      const finish = async () => {
        try {
          const detail = await getThread(threadId);
          setMessages(detail.messages);
        } catch (err) {
          handleFailure(err, "could not reload the thread");
        }
        setLiveTurn(null);
        void refreshThreads();
      };

      try {
        await streamMessage(
          threadId,
          content,
          {
            onStep: (step) =>
              setLiveTurn((turn) =>
                turn ? { ...turn, steps: [...turn.steps, step] } : turn,
              ),
            onCitations: (citations) =>
              setLiveTurn((turn) => (turn ? { ...turn, citations } : turn)),
            onDelta: (text) =>
              setLiveTurn((turn) =>
                turn ? { ...turn, draft: turn.draft + text } : turn,
              ),
            onDone: () => void finish(),
            onError: (detail) => {
              setError(detail);
              setLiveTurn(null);
            },
          },
          controller.signal,
        );
      } catch (err) {
        if (!controller.signal.aborted) {
          handleFailure(err, "the chat request failed");
          setLiveTurn(null);
        }
      }
    },
    [activeThreadId, messages.length, handleFailure, refreshThreads],
  );

  const lastAssistant = [...messages]
    .reverse()
    .find((message) => message.role === "assistant");
  const panelCitations = liveTurn?.citations.length
    ? liveTurn.citations
    : (lastAssistant?.citations ?? []);

  return (
    <div className="workspace">
      <ThreadSidebar
        threads={threads}
        activeThreadId={activeThreadId}
        email={email}
        view={view}
        onSelect={(threadId) => void openThread(threadId)}
        onNewThread={newThread}
        onSignOut={signOut}
        onViewChange={setView}
      />
      {view === "audit" ? (
        <AuditPanel />
      ) : (
        <>
          <ChatView
            messages={messages}
            liveTurn={liveTurn}
            error={error}
            onSend={(content) => void send(content)}
            onMarkerClick={setHighlightMarker}
          />
          <CitationPanel
            citations={panelCitations}
            highlightMarker={highlightMarker}
          />
        </>
      )}
    </div>
  );
}
