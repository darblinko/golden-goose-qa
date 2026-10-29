export type Role = "admin" | "qa_user" | "auditor_readonly";

export interface Thread {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  marker: number;
  doc_key: string;
  doc_type: string;
  title: string;
  revision: string | null;
  section_path: string | null;
  page: number | null;
  citation: string;
  provenance?: "internal" | "external";
}

export interface TraceEvent {
  event: string;
  node?: string;
  [key: string]: unknown;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  verdict: string | null;
  citations: Citation[];
  trace: TraceEvent[];
  created_at: string;
}

export interface ThreadDetail {
  thread: Thread;
  messages: Message[];
}

export type Verdict = "grounded" | "insufficient_evidence" | "not_applicable";

export interface StreamHandlers {
  onStep: (step: TraceEvent) => void;
  onCitations: (citations: Citation[]) => void;
  onDelta: (text: string) => void;
  onDone: (payload: { message_id: string; verdict: string | null }) => void;
  onError: (detail: string) => void;
}

export interface AuditCheck {
  check_id: string;
  title: string;
  description: string;
  kind: string;
  defect_kind: string | null;
}

export interface AuditCollection {
  collection_id: string;
  title: string;
  description: string;
  checks: AuditCheck[];
}

export interface AuditCheckResult {
  check_id: string;
  title: string;
  kind: string;
  defect_kind: string | null;
  status: "pass" | "finding" | "error";
  columns: string[];
  rows: Record<string, unknown>[];
  truncated: boolean;
  source: string;
  detail: string;
}

export interface AuditReport {
  collection_id: string | null;
  summary: string;
  advisory: string;
  results: AuditCheckResult[];
}
