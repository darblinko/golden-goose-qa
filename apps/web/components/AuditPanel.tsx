"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, listAuditCollections, runAuditReport } from "@/lib/api";
import type {
  AuditCheckResult,
  AuditCollection,
  AuditReport,
} from "@/lib/types";

const STATUS_LABEL: Record<AuditCheckResult["status"], string> = {
  pass: "Pass",
  finding: "Finding",
  error: "Error",
};

function ResultRows({ result }: { result: AuditCheckResult }) {
  if (result.status === "error") {
    return <p className="audit-check-detail">{result.detail}</p>;
  }
  if (result.rows.length === 0) {
    return null;
  }
  return (
    <div className="audit-table-wrap">
      <table className="audit-table">
        <thead>
          <tr>
            {result.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, index) => (
            <tr key={index}>
              {result.columns.map((column) => (
                <td key={column}>{String(row[column] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {result.truncated && (
        <p className="audit-check-detail">Rows truncated by the tool limit.</p>
      )}
    </div>
  );
}

function CheckResultCard({ result }: { result: AuditCheckResult }) {
  return (
    <section className="audit-check">
      <header className="audit-check-header">
        <span className={`audit-badge ${result.status}`}>
          {STATUS_LABEL[result.status]}
          {result.status === "finding" ? ` (${result.rows.length})` : ""}
        </span>
        <span className="audit-check-title">{result.title}</span>
        <span className="audit-check-kind">{result.kind}</span>
      </header>
      <ResultRows result={result} />
    </section>
  );
}

export default function AuditPanel() {
  const [collections, setCollections] = useState<AuditCollection[]>([]);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAuditCollections()
      .then(setCollections)
      .catch((err) =>
        setError(
          err instanceof ApiError
            ? err.message
            : "could not load audit collections",
        ),
      );
  }, []);

  const run = useCallback(async (collectionId?: string) => {
    setRunning(true);
    setError(null);
    try {
      setReport(await runAuditReport(collectionId));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "the audit report failed",
      );
    } finally {
      setRunning(false);
    }
  }, []);

  return (
    <div className="audit-panel">
      <div className="audit-controls">
        <h1 className="audit-heading">Audit prep</h1>
        <p className="audit-subheading">
          Deterministic readiness checks over the derived registers and
          knowledge graph. A finding is a gate that returned rows.
        </p>
        <button
          className="btn-primary"
          disabled={running}
          onClick={() => void run()}
        >
          {running ? "Running…" : "Run all checks"}
        </button>
        <div className="audit-collections">
          {collections.map((collection) => (
            <button
              key={collection.collection_id}
              className="audit-collection"
              disabled={running}
              onClick={() => void run(collection.collection_id)}
              title={collection.description}
            >
              <span className="audit-collection-title">{collection.title}</span>
              <span className="audit-collection-count">
                {collection.checks.length} checks
              </span>
            </button>
          ))}
        </div>
        {error && <p className="form-error">{error}</p>}
      </div>
      {report && (
        <div className="audit-report">
          <p className="audit-summary">{report.summary}</p>
          {report.advisory && report.advisory !== report.summary && (
            <p className="audit-advisory">{report.advisory}</p>
          )}
          {report.results.map((result) => (
            <CheckResultCard key={result.check_id} result={result} />
          ))}
        </div>
      )}
    </div>
  );
}
