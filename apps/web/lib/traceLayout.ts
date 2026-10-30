/* Seeded force-directed layout for the trace graph. The anchor is pinned at
   the centre; hop 1 and hop 2 nodes are held near two elliptical rings and
   start from a radial tree arrangement, so the result reads as rings around
   the anchor rather than a free-floating cloud. Every function is pure: the
   same inputs and seed always give the same positions. */

import {
  type Buffers,
  type LayoutEdge,
  type LayoutModel,
  type LayoutNode,
  type Point,
  type Ring,
  EDGE_MARGIN,
  LABEL_GAP,
  LAYOUT_TICKS,
  tickOnce,
} from "./traceForces";

export {
  type LabelSide,
  type LayoutEdge,
  type LayoutNode,
  type Point,
  LABEL_GAP,
  LAYOUT_TICKS,
  labelSide,
} from "./traceForces";

export interface LayoutState {
  readonly model: LayoutModel;
  readonly xs: readonly number[];
  readonly ys: readonly number[];
  readonly vx: readonly number[];
  readonly vy: readonly number[];
  readonly tick: number;
}

const TWO_PI = Math.PI * 2;
const START_SCALE = 0.3;

export function hashSeed(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function ringRadii(nodes: readonly LayoutNode[], width: number, height: number): Ring[] {
  const outerNodes = nodes.filter((node) => node.hop > 0);
  const widest = Math.max(0, ...outerNodes.map((node) => node.labelWidth));
  const tallest = Math.max(0, ...outerNodes.map((node) => node.labelHeight));
  const outer = {
    rx: Math.max(60, width / 2 - Math.min(widest, 160) - LABEL_GAP - 10 - EDGE_MARGIN),
    ry: Math.max(60, height / 2 - tallest - LABEL_GAP - 10 - EDGE_MARGIN),
  };
  const innerScale = nodes.some((node) => node.hop >= 2) ? 0.5 : 0.8;
  return [
    { rx: 0, ry: 0 },
    { rx: outer.rx * innerScale, ry: outer.ry * innerScale },
    outer,
  ];
}

function byGroupThenId(nodes: readonly LayoutNode[]) {
  return (a: number, b: number): number => {
    const left = nodes[a]!;
    const right = nodes[b]!;
    if (left.group !== right.group) return left.group < right.group ? -1 : 1;
    return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
  };
}

function parentsOfOuterNodes(
  nodes: readonly LayoutNode[],
  links: readonly (readonly [number, number])[],
): Map<number, number[]> {
  const children = new Map<number, number[]>();
  const placed = new Set<number>();
  for (const [a, b] of links) {
    const pairs: [number, number][] = [[a, b], [b, a]];
    for (const [parent, child] of pairs) {
      if (nodes[parent]!.hop !== 1 || nodes[child]!.hop < 2 || placed.has(child)) continue;
      placed.add(child);
      children.set(parent, [...(children.get(parent) ?? []), child]);
    }
  }
  return children;
}

/** Radial tree angles: each hop 1 node gets a sector sized by its number of
 * hop 2 children, and the children spread across that sector. */
function homeAngles(
  nodes: readonly LayoutNode[],
  links: readonly (readonly [number, number])[],
  random: () => number,
): number[] {
  const angles = nodes.map(() => random() * TWO_PI);
  const order = byGroupThenId(nodes);
  const firstRing = nodes.map((_, i) => i).filter((i) => nodes[i]!.hop === 1).sort(order);
  const children = parentsOfOuterNodes(nodes, links);
  const weight = (i: number) => 1 + 0.8 * (children.get(i)?.length ?? 0);
  const total = firstRing.reduce((sum, i) => sum + weight(i), 0);
  let cursor = random() * TWO_PI;
  for (const parent of firstRing) {
    const span = (TWO_PI * weight(parent)) / total;
    angles[parent] = cursor + span / 2;
    const kids = [...(children.get(parent) ?? [])].sort(order);
    kids.forEach((kid, k) => {
      angles[kid] = cursor + (span * (k + 0.5)) / kids.length;
    });
    cursor += span;
  }
  return angles;
}

export function createLayout(
  nodes: readonly LayoutNode[],
  edges: readonly LayoutEdge[],
  width: number,
  height: number,
  seed: number,
): LayoutState {
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const links = edges
    .map((edge) => [index.get(edge.source), index.get(edge.target)] as const)
    .filter((pair): pair is readonly [number, number] =>
      pair[0] !== undefined && pair[1] !== undefined && pair[0] !== pair[1],
    );
  const degree = nodes.map(() => 0);
  for (const [a, b] of links) {
    degree[a]! += 1;
    degree[b]! += 1;
  }
  const random = seededRandom(seed);
  const angles = homeAngles(nodes, links, random);
  const rings = ringRadii(nodes, width, height);
  const home = nodes.map((node, i) => {
    const ring = rings[Math.min(Math.max(node.hop, 0), 2)]!;
    return {
      x: width / 2 + ring.rx * Math.cos(angles[i]!),
      y: height / 2 + ring.ry * Math.sin(angles[i]!),
    };
  });
  const model = { nodes, links, degree, home, rings, width, height };
  const jitter = () => (random() - 0.5) * 6;
  const xs = home.map((p) => width / 2 + (p.x - width / 2) * START_SCALE + jitter());
  const ys = home.map((p) => height / 2 + (p.y - height / 2) * START_SCALE + jitter());
  return { model, xs, ys, vx: nodes.map(() => 0), vy: nodes.map(() => 0), tick: 0 };
}

/** Advances the layout by `ticks` steps and returns a new state; the input
 * state is not modified. */
export function stepLayout(state: LayoutState, ticks: number): LayoutState {
  const steps = Math.max(0, Math.min(ticks, LAYOUT_TICKS - state.tick));
  if (steps === 0) return state;
  const buffers: Buffers = {
    xs: [...state.xs],
    ys: [...state.ys],
    vx: [...state.vx],
    vy: [...state.vy],
  };
  for (let k = 0; k < steps; k += 1) {
    tickOnce(state.model, buffers, state.tick + k);
  }
  return { model: state.model, ...buffers, tick: state.tick + steps };
}

export function layoutPositions(state: LayoutState): Map<string, Point> {
  return new Map(
    state.model.nodes.map((node, i) => [node.id, { x: state.xs[i]!, y: state.ys[i]! }]),
  );
}

export function computeTraceLayout(
  nodes: readonly LayoutNode[],
  edges: readonly LayoutEdge[],
  width: number,
  height: number,
  seed: number,
): Map<string, Point> {
  const settled = stepLayout(createLayout(nodes, edges, width, height, seed), LAYOUT_TICKS);
  return layoutPositions(settled);
}
