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
import type { Message, Thread } from "@/lib/types";
import {
  type CitationSelection,
  type LiveTurn,
  liveTurnForThread,
  panelCitations,
} from "@/lib/workspaceState";
import AuditPanel from "./AuditPanel";
import ChatView from "./ChatView";
import CitationPanel from "./CitationPanel";
import ThreadSidebar, { type WorkspaceView } from "./ThreadSidebar";
import TraceView from "./TraceView";

export type { LiveTurn };

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
  const [selection, setSelection] = useState<CitationSelection | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // The thread on screen, readable from stream callbacks that outlive a
  // render: a response for another thread must not replace this one's view.
  const activeThreadRef = useRef<string | null>(null);
  const requestCounter = useRef(0);

  const showThread = useCallback((threadId: string | null) => {
    activeThreadRef.current = threadId;
    setActiveThreadId(threadId);
  }, []);

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
      showThread(threadId);
      setSelection(null);
      try {
        const detail = await getThread(threadId);
        if (activeThreadRef.current === threadId) setMessages(detail.messages);
      } catch (err) {
        handleFailure(err, "could not load the thread");
      }
    },
    [handleFailure, showThread],
  );

  const newThread = useCallback(() => {
    setView("chat");
    showThread(null);
    setMessages([]);
    setSelection(null);
    setError(null);
  }, [showThread]);

  const send = useCallback(
    async (content: string) => {
      setError(null);
      setSelection(null);
      let threadId = activeThreadId;
      try {
        if (!threadId) {
          const thread = await createThread();
          threadId = thread.id;
          showThread(threadId);
        }
      } catch (err) {
        handleFailure(err, "could not create a thread");
        return;
      }

      const requestId = ++requestCounter.current;
      const userMessage: Message = {
        id: `local-${requestId}`,
        role: "user",
        content,
        verdict: null,
        citations: [],
        trace: [],
        created_at: "",
      };
      setMessages((current) => [...current, userMessage]);
      setLiveTurn({ threadId, requestId, steps: [], draft: "", citations: [] });

      const isCurrent = () => activeThreadRef.current === threadId;
      // Updates apply only to this request's own live turn.
      const updateTurn = (change: (turn: LiveTurn) => LiveTurn) =>
        setLiveTurn((turn) =>
          turn && turn.requestId === requestId ? change(turn) : turn,
        );
      const endTurn = () =>
        setLiveTurn((turn) =>
          turn && turn.requestId === requestId ? null : turn,
        );

      const controller = new AbortController();
      abortRef.current = controller;
      const finish = async () => {
        try {
          const detail = await getThread(threadId);
          if (isCurrent()) setMessages(detail.messages);
        } catch (err) {
          handleFailure(err, "could not reload the thread");
        }
        endTurn();
        void refreshThreads();
      };

      try {
        await streamMessage(
          threadId,
          content,
          {
            onStep: (step) =>
              updateTurn((turn) => ({ ...turn, steps: [...turn.steps, step] })),
            onCitations: (citations) =>
              updateTurn((turn) => ({ ...turn, citations })),
            onDelta: (text) =>
              updateTurn((turn) => ({ ...turn, draft: turn.draft + text })),
            onDone: () => void finish(),
            onError: (detail) => {
              if (isCurrent()) setError(detail);
              endTurn();
            },
          },
          controller.signal,
        );
      } catch (err) {
        if (!controller.signal.aborted) {
          if (isCurrent()) handleFailure(err, "the chat request failed");
          endTurn();
        }
      }
    },
    [activeThreadId, handleFailure, refreshThreads, showThread],
  );

  const visibleTurn = liveTurnForThread(liveTurn, activeThreadId);
  const citationsShown = panelCitations(messages, visibleTurn, selection);

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
      ) : view === "trace" ? (
        <TraceView />
      ) : (
        <>
          <ChatView
            messages={messages}
            liveTurn={visibleTurn}
            busy={liveTurn !== null}
            error={error}
            onSend={(content) => void send(content)}
            onMarkerClick={(messageId, marker) =>
              setSelection({ messageId, marker })
            }
          />
          <CitationPanel
            citations={citationsShown}
            highlightMarker={selection?.marker ?? null}
          />
        </>
      )}
    </div>
  );
}
