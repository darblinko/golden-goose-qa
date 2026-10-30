"use client";

import type { Thread } from "@/lib/types";

export type WorkspaceView = "chat" | "audit" | "trace";

export default function ThreadSidebar({
  threads,
  activeThreadId,
  email,
  view,
  onSelect,
  onNewThread,
  onSignOut,
  onViewChange,
}: {
  threads: Thread[];
  activeThreadId: string | null;
  email: string;
  view: WorkspaceView;
  onSelect: (threadId: string) => void;
  onNewThread: () => void;
  onSignOut: () => void;
  onViewChange: (view: WorkspaceView) => void;
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="brand">Golden Goose</span>
        <button className="new-thread-btn" onClick={onNewThread}>
          + New
        </button>
      </div>
      <div className="view-tabs">
        <button
          className={`view-tab${view === "chat" ? " active" : ""}`}
          onClick={() => onViewChange("chat")}
        >
          Chat
        </button>
        <button
          className={`view-tab${view === "audit" ? " active" : ""}`}
          onClick={() => onViewChange("audit")}
        >
          Audit prep
        </button>
        <button
          className={`view-tab${view === "trace" ? " active" : ""}`}
          onClick={() => onViewChange("trace")}
        >
          Trace
        </button>
      </div>
      <nav className="thread-list">
        {threads.map((thread) => (
          <button
            key={thread.id}
            className={`thread-item${thread.id === activeThreadId ? " active" : ""}`}
            onClick={() => onSelect(thread.id)}
            title={thread.title}
          >
            {thread.title || "Untitled"}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="email" title={email}>
          {email}
        </span>
        <button className="signout-btn" onClick={onSignOut}>
          Sign out
        </button>
      </div>
    </aside>
  );
}
