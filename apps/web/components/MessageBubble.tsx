"use client";

import { Fragment } from "react";
import type { Message } from "@/lib/types";

const VERDICT_LABELS: Record<string, string> = {
  grounded: "Grounded",
  insufficient_evidence: "Insufficient evidence",
  not_applicable: "Not applicable",
};

/** Splits answer text on [n] citation markers so they render as clickable
 * references wired to the citation panel. */
function renderWithMarkers(
  content: string,
  onMarkerClick: (marker: number) => void,
) {
  const parts = content.split(/(\[\d+\])/g);
  return parts.map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (!match || match[1] === undefined) {
      return <Fragment key={index}>{part}</Fragment>;
    }
    const marker = Number(match[1]);
    return (
      <button
        key={index}
        className="marker"
        onClick={() => onMarkerClick(marker)}
      >
        [{marker}]
      </button>
    );
  });
}

export default function MessageBubble({
  message,
  onMarkerClick,
}: {
  message: Message;
  onMarkerClick: (marker: number) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="message user">
        <div className="bubble">{message.content}</div>
      </div>
    );
  }
  return (
    <div className="message assistant">
      <div className="bubble">
        {renderWithMarkers(message.content, onMarkerClick)}
      </div>
      {message.verdict ? (
        <div className="verdict-row">
          <span className={`verdict-badge verdict-${message.verdict}`}>
            {VERDICT_LABELS[message.verdict] ?? message.verdict}
          </span>
          {message.citations.length > 0 ? (
            <span>
              {message.citations.length} source
              {message.citations.length === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
