"use client";

import { Fragment } from "react";
import { kindGroup, kindName } from "@/lib/traceStyle";
import type {
  TraceGraph,
  TraceGraphEdge,
  TraceGraphNode,
} from "@/lib/types";

interface NodeLink {
  edge: TraceGraphEdge;
  other: TraceGraphNode | undefined;
  outgoing: boolean;
}

function linksOf(graph: TraceGraph, node: TraceGraphNode): NodeLink[] {
  const byId = new Map(graph.nodes.map((item) => [item.id, item]));
  return graph.edges
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => {
      const outgoing = edge.source === node.id;
      return { edge, outgoing, other: byId.get(outgoing ? edge.target : edge.source) };
    })
    .sort((a, b) => {
      if (a.edge.confidence !== b.edge.confidence) {
        return b.edge.confidence - a.edge.confidence;
      }
      return (a.other?.key ?? "").localeCompare(b.other?.key ?? "");
    });
}

function keyOf(graph: TraceGraph, id: string): string {
  return graph.nodes.find((node) => node.id === id)?.key ?? id;
}

function LinkItem({
  graph,
  link,
  onSelect,
}: {
  graph: TraceGraph;
  link: NodeLink;
  onSelect: (id: string) => void;
}) {
  const { edge, other, outgoing } = link;
  const otherId = outgoing ? edge.target : edge.source;
  return (
    <div className="trace-link">
      <div className="trace-link-head">
        <span className="trace-link-dir">{outgoing ? "to" : "from"}</span>
        <button className="trace-link-node" onClick={() => onSelect(otherId)}>
          {other?.key ?? otherId}
        </button>
        <span className={`trace-badge ${edge.inferred ? "inferred" : "recorded"}`}>
          {edge.inferred ? "Inferred" : "Recorded"}
        </span>
      </div>
      <div className="trace-link-triple">
        {keyOf(graph, edge.source)} <strong>{edge.type}</strong>{" "}
        {keyOf(graph, edge.target)}
      </div>
      <dl className="trace-meta">
        <dt>Method</dt>
        <dd>{edge.method}</dd>
        <dt>Locator</dt>
        <dd>{edge.locator || "none recorded"}</dd>
        <dt>Source document</dt>
        <dd>{edge.source_doc_key}</dd>
        <dt>Confidence</dt>
        <dd>{edge.confidence.toFixed(2)}</dd>
      </dl>
    </div>
  );
}

function RecordSummary({
  graph,
  node,
  shownLinks,
  onRecentre,
}: {
  graph: TraceGraph;
  node: TraceGraphNode;
  shownLinks: number;
  onRecentre: (id: string) => void;
}) {
  const properties = Object.entries(node.properties).filter(
    ([, value]) => value !== null && value !== "",
  );
  return (
    <div className="trace-record">
      <div className={`trace-record-kind kind-${kindGroup(node.kind)}`}>
        <span className="trace-swatch" aria-hidden="true" />
        {kindName(node.kind)}
        {node.id === graph.anchor ? " (anchor)" : ""}
      </div>
      <div className="trace-record-key">{node.key}</div>
      {node.title && <div className="trace-record-title">{node.title}</div>}
      {properties.length > 0 && (
        <dl className="trace-meta">
          {properties.map(([name, value]) => (
            <Fragment key={name}>
              <dt>{name}</dt>
              <dd>{String(value)}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      <p className="trace-record-links">
        {shownLinks} {shownLinks === 1 ? "link" : "links"} shown
        {node.hidden_links > 0
          ? `, ${node.hidden_links} more in the graph not drawn here`
          : ""}
      </p>
      {node.id !== graph.anchor && (
        <button className="btn-secondary" onClick={() => onRecentre(node.id)}>
          Centre on this record
        </button>
      )}
    </div>
  );
}

export default function TraceNodePanel({
  graph,
  node,
  onSelect,
  onRecentre,
}: {
  graph: TraceGraph | null;
  node: TraceGraphNode | null;
  onSelect: (id: string) => void;
  onRecentre: (id: string) => void;
}) {
  if (!graph || !node) {
    return (
      <aside className="trace-panel">
        <div className="trace-panel-header">Record</div>
        <div className="trace-panel-empty">
          The traced record and the provenance of each of its links appear
          here. Select a node to inspect it.
        </div>
      </aside>
    );
  }
  const links = linksOf(graph, node);
  return (
    <aside className="trace-panel">
      <div className="trace-panel-header">
        {node.id === graph.anchor ? "Anchor record" : "Selected record"}
      </div>
      <RecordSummary
        graph={graph}
        node={node}
        shownLinks={links.length}
        onRecentre={onRecentre}
      />
      <div className="trace-panel-header">Links ({links.length})</div>
      {links.length === 0 && (
        <div className="trace-panel-empty">No links are drawn for this record.</div>
      )}
      {links.map((link) => (
        <LinkItem key={link.edge.id} graph={graph} link={link} onSelect={onSelect} />
      ))}
    </aside>
  );
}
