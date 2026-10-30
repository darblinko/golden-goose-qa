// Run with: npm test (node --test with type stripping; no extra dependencies).
import assert from "node:assert/strict";
import { test } from "node:test";
import type { Citation, Message } from "./types";
import {
  type LiveTurn,
  liveTurnForThread,
  panelCitations,
} from "./workspaceState.ts";

function citation(marker: number, docKey: string): Citation {
  return {
    marker,
    doc_key: docKey,
    doc_type: "sop",
    title: docKey,
    revision: "A",
    section_path: null,
    page: null,
    citation: `${docKey} Rev A`,
  };
}

function assistant(id: string, citations: Citation[]): Message {
  return {
    id,
    role: "assistant",
    content: "answer [1]",
    verdict: "grounded",
    citations,
    trace: [],
    created_at: "",
  };
}

const first = assistant("m1", [citation(1, "SOP-001")]);
const second = assistant("m2", [citation(1, "SOP-002")]);

test("a marker in an earlier answer selects that answer's sources", () => {
  const shown = panelCitations([first, second], null, {
    messageId: "m1",
    marker: 1,
  });
  assert.deepEqual(
    shown.map((c) => c.doc_key),
    ["SOP-001"],
  );
});

test("without a selection the latest answer's sources are shown", () => {
  const shown = panelCitations([first, second], null, null);
  assert.deepEqual(
    shown.map((c) => c.doc_key),
    ["SOP-002"],
  );
});

test("a live turn's citations win until a marker is clicked", () => {
  const live: LiveTurn = {
    threadId: "t1",
    requestId: 1,
    steps: [],
    draft: "",
    citations: [citation(1, "SOP-009")],
  };
  assert.deepEqual(
    panelCitations([first], live, null).map((c) => c.doc_key),
    ["SOP-009"],
  );
});

test("a turn streaming in thread A is not shown in thread B", () => {
  const live: LiveTurn = {
    threadId: "thread-a",
    requestId: 1,
    steps: [],
    draft: "partial",
    citations: [],
  };
  assert.equal(liveTurnForThread(live, "thread-b"), null);
  assert.equal(liveTurnForThread(live, "thread-a"), live);
});
