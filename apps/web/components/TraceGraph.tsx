"use client";

import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  LABEL_GAP,
  type LabelSide,
  type LayoutNode,
  type Point,
  hashSeed,
  labelSide,
} from "@/lib/traceLayout";
import {
  BADGE_FONT_SIZE,
  BADGE_GAP,
  BADGE_PAD_X,
  kindGroup,
  kindName,
  nodeMetrics,
  truncateKey,
} from "@/lib/traceStyle";
import type { TraceGraph as TraceGraphData, TraceGraphNode } from "@/lib/types";
import { type Size, useElementSize, useTraceLayout } from "./useTraceLayout";

interface NodeView {
  node: TraceGraphNode;
  layout: LayoutNode;
  text: string;
  textWidth: number;
  badge: string | null;
  badgeWidth: number;
  fontSize: number;
}

function textMeasurer(): (text: string, size: number, weight: number) => number {
  const context = document.createElement("canvas").getContext("2d");
  const family = getComputedStyle(document.body).fontFamily || "sans-serif";
  return (text, size, weight) => {
    if (!context) return text.length * size * 0.62;
    context.font = `${weight} ${size}px ${family}`;
    return Math.ceil(context.measureText(text).width);
  };
}

function byHopThenKey(a: TraceGraphNode, b: TraceGraphNode): number {
  if (a.hop !== b.hop) return a.hop - b.hop;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

/** Sorted by hop so keyboard focus moves outwards from the anchor. */
function buildNodeViews(graph: TraceGraphData): NodeView[] {
  const measure = textMeasurer();
  return [...graph.nodes].sort(byHopThenKey).map((node) => {
    const { radius, fontSize, fontWeight } = nodeMetrics(node.hop);
    const text = truncateKey(node.key);
    const textWidth = measure(text, fontSize, fontWeight);
    const badge = node.hidden_links > 0 ? `+${node.hidden_links}` : null;
    const badgeWidth = badge
      ? measure(badge, BADGE_FONT_SIZE, 700) + BADGE_PAD_X * 2
      : 0;
    const layout: LayoutNode = {
      id: node.id,
      hop: node.hop,
      group: kindGroup(node.kind),
      radius,
      labelWidth: textWidth + (badge ? BADGE_GAP + badgeWidth : 0),
      labelHeight: Math.ceil(fontSize * 1.3),
    };
    return { node, layout, text, textWidth, badge, badgeWidth, fontSize };
  });
}

function neighbourMap(graph: TraceGraphData): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  const link = (from: string, to: string) => {
    const set = map.get(from) ?? new Set<string>();
    set.add(to);
    map.set(from, set);
  };
  for (const edge of graph.edges) {
    link(edge.source, edge.target);
    link(edge.target, edge.source);
  }
  return map;
}

function labelGeometry(view: NodeView, point: Point, side: LabelSide) {
  const r = view.layout.radius;
  const badgeSpan = view.badge ? BADGE_GAP + view.badgeWidth : 0;
  if (side === "right" || side === "left") {
    const textX = side === "right" ? point.x + r + LABEL_GAP : point.x - r - LABEL_GAP;
    const badgeX =
      side === "right"
        ? textX + view.textWidth + BADGE_GAP
        : textX - view.textWidth - badgeSpan;
    const anchor = side === "right" ? "start" : "end";
    return { textX, textY: point.y, anchor, badgeX } as const;
  }
  const offset = r + LABEL_GAP + view.layout.labelHeight / 2;
  const left = point.x - (view.textWidth + badgeSpan) / 2;
  const textY = side === "above" ? point.y - offset : point.y + offset;
  return {
    textX: left + view.textWidth / 2,
    textY,
    anchor: "middle",
    badgeX: left + view.textWidth + BADGE_GAP,
  } as const;
}

function NodeLabel({ view, point, size }: { view: NodeView; point: Point; size: Size }) {
  const side = labelSide(point, size.width, size.height, view.node.hop);
  const { textX, textY, anchor, badgeX } = labelGeometry(view, point, side);
  const badgeHeight = BADGE_FONT_SIZE + 5;
  return (
    <>
      <text
        className="trace-node-label"
        x={textX}
        y={textY}
        textAnchor={anchor}
        dominantBaseline="central"
        fontSize={view.fontSize}
      >
        {view.text}
      </text>
      {view.badge && (
        <g className="trace-node-badge">
          <rect
            x={badgeX}
            y={textY - badgeHeight / 2}
            width={view.badgeWidth}
            height={badgeHeight}
            rx={badgeHeight / 2}
          />
          <text
            x={badgeX + view.badgeWidth / 2}
            y={textY}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={BADGE_FONT_SIZE}
          >
            {view.badge}
          </text>
        </g>
      )}
    </>
  );
}

function nodeAriaLabel(node: TraceGraphNode): string {
  const parts = [`${kindName(node.kind)} ${node.key}`];
  if (node.title) parts.push(node.title);
  parts.push(`${node.degree} links`);
  return parts.join(", ");
}

interface GraphNodeProps {
  view: NodeView;
  point: Point;
  size: Size;
  selected: boolean;
  dimmed: boolean;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}

function GraphNode(props: GraphNodeProps) {
  const { view, point, size, selected, dimmed, onSelect, onHover } = props;
  const { node, layout } = view;
  const onKeyDown = (event: KeyboardEvent<SVGGElement>) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onSelect(node.id);
  };
  const classes = [
    "trace-node",
    `kind-${layout.group}`,
    node.hop === 0 ? "anchor" : `hop-${Math.min(node.hop, 2)}`,
    selected ? "selected" : "",
    dimmed ? "dim" : "",
  ];
  return (
    <g
      className={classes.filter(Boolean).join(" ")}
      tabIndex={0}
      role="button"
      aria-label={nodeAriaLabel(node)}
      aria-pressed={selected}
      onClick={() => onSelect(node.id)}
      onKeyDown={onKeyDown}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(node.id)}
      onBlur={() => onHover(null)}
    >
      <circle className="trace-node-hit" cx={point.x} cy={point.y} r={layout.radius + 7} />
      {node.hop === 0 && (
        <circle className="trace-node-halo" cx={point.x} cy={point.y} r={layout.radius + 9} />
      )}
      <circle className="trace-node-focus" cx={point.x} cy={point.y} r={layout.radius + 7} />
      <circle className="trace-node-ring" cx={point.x} cy={point.y} r={layout.radius + 3.5} />
      <circle className="trace-node-dot" cx={point.x} cy={point.y} r={layout.radius} />
      <NodeLabel view={view} point={point} size={size} />
    </g>
  );
}

function EdgeLines({
  graph,
  positions,
  hoverId,
}: {
  graph: TraceGraphData;
  positions: Map<string, Point>;
  hoverId: string | null;
}) {
  return (
    <g className="trace-edges">
      {graph.edges.map((edge) => {
        const from = positions.get(edge.source);
        const to = positions.get(edge.target);
        if (!from || !to) return null;
        const touchesAnchor =
          edge.source === graph.anchor || edge.target === graph.anchor;
        const touchesHover = hoverId === edge.source || hoverId === edge.target;
        const classes = [
          "trace-edge",
          edge.inferred ? "inferred" : "recorded",
          touchesAnchor ? "primary" : "",
          hoverId ? (touchesHover ? "active" : "dim") : "",
        ];
        return (
          <line
            key={edge.id}
            className={classes.filter(Boolean).join(" ")}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
          />
        );
      })}
    </g>
  );
}

interface TraceGraphProps {
  graph: TraceGraphData;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function TraceGraph({ graph, selectedId, onSelect }: TraceGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const size = useElementSize(containerRef);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const views = useMemo(() => buildNodeViews(graph), [graph]);
  const layoutNodes = useMemo(() => views.map((view) => view.layout), [views]);
  const neighbours = useMemo(() => neighbourMap(graph), [graph]);
  const seed = useMemo(
    () => hashSeed(`${graph.anchor}|${graph.nodes.length}|${graph.edges.length}`),
    [graph],
  );
  const positions = useTraceLayout(layoutNodes, graph.edges, size, seed);
  const related = hoverId ? (neighbours.get(hoverId) ?? new Set<string>()) : null;
  const isDimmed = (id: string) => related !== null && id !== hoverId && !related.has(id);

  return (
    <div className="trace-graph" ref={containerRef}>
      {size && positions && (
        <svg
          width={size.width}
          height={size.height}
          viewBox={`0 0 ${size.width} ${size.height}`}
          role="group"
          aria-label={`Links around ${graph.anchor}`}
        >
          <EdgeLines graph={graph} positions={positions} hoverId={hoverId} />
          <g className="trace-nodes">
            {views.map((view) => {
              const point = positions.get(view.node.id);
              if (!point) return null;
              return (
                <GraphNode
                  key={view.node.id}
                  view={view}
                  point={point}
                  size={size}
                  selected={view.node.id === selectedId}
                  dimmed={isDimmed(view.node.id)}
                  onSelect={onSelect}
                  onHover={setHoverId}
                />
              );
            })}
          </g>
        </svg>
      )}
    </div>
  );
}
