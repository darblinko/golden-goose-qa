/* Per-tick forces for the trace layout: link springs, repulsion, a pull
   towards each node's ring and home angle, and label-aware collision. The
   functions mutate the scratch buffers handed to them by stepLayout. */

export interface LayoutNode {
  id: string;
  hop: number;
  group: string;
  radius: number;
  labelWidth: number;
  labelHeight: number;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

export interface Point {
  x: number;
  y: number;
}

export type LabelSide = "right" | "left" | "above" | "below";

export interface Ring {
  rx: number;
  ry: number;
}

export interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface LayoutModel {
  nodes: readonly LayoutNode[];
  links: readonly (readonly [number, number])[];
  degree: readonly number[];
  home: readonly Point[];
  rings: readonly Ring[];
  width: number;
  height: number;
}

export const LAYOUT_TICKS = 160;
export const LABEL_GAP = 5;
export const EDGE_MARGIN = 8;

/* Force scale per tick. Low enough that the graph visibly forms across all
   LAYOUT_TICKS instead of snapping into place in the first few. */
const FORCE_SCALE = 0.06;
const VELOCITY_KEEP = 0.55;
const BOX_PAD = 3;
const LINK_LENGTH = 70;
const LINK_STRENGTH = 0.35;
const CHARGE = 260;
const CHARGE_RANGE = 220;
const RADIAL_STRENGTH = 0.22;
const HOME_STRENGTH = 0.07;

/** Where a node's label sits: away from the centre, so labels on the first
 * ring do not cross the anchor's own edges. */
export function labelSide(
  point: Point,
  width: number,
  height: number,
  hop: number,
): LabelSide {
  if (hop === 0) return "below";
  const dx = point.x - width / 2;
  const dy = point.y - height / 2;
  const length = Math.hypot(dx, dy) || 1;
  if (Math.abs(dx / length) >= 0.4) return dx > 0 ? "right" : "left";
  return dy < 0 ? "above" : "below";
}

function nodeBox(node: LayoutNode, point: Point, side: LabelSide): Box {
  const r = node.radius;
  const box = { x1: point.x - r, y1: point.y - r, x2: point.x + r, y2: point.y + r };
  const w = node.labelWidth;
  const h = node.labelHeight;
  if (side === "right") box.x2 = point.x + r + LABEL_GAP + w;
  if (side === "left") box.x1 = point.x - r - LABEL_GAP - w;
  if (side === "right" || side === "left") {
    box.y1 = Math.min(box.y1, point.y - h / 2);
    box.y2 = Math.max(box.y2, point.y + h / 2);
  } else {
    box.x1 = Math.min(box.x1, point.x - w / 2);
    box.x2 = Math.max(box.x2, point.x + w / 2);
    if (side === "above") box.y1 = point.y - r - LABEL_GAP - h;
    else box.y2 = point.y + r + LABEL_GAP + h;
  }
  return {
    x1: box.x1 - BOX_PAD,
    y1: box.y1 - BOX_PAD,
    x2: box.x2 + BOX_PAD,
    y2: box.y2 + BOX_PAD,
  };
}

function ringOf(model: LayoutModel, node: LayoutNode): Ring {
  return model.rings[Math.min(Math.max(node.hop, 0), 2)]!;
}

export interface Buffers {
  xs: number[];
  ys: number[];
  vx: number[];
  vy: number[];
}

function applyLinks(model: LayoutModel, b: Buffers, alpha: number): void {
  for (const [s, t] of model.links) {
    if (model.nodes[s]!.hop === 0 || model.nodes[t]!.hop === 0) continue;
    const dx = b.xs[t]! - b.xs[s]!;
    const dy = b.ys[t]! - b.ys[s]!;
    const distance = Math.hypot(dx, dy) || 1;
    const strength = LINK_STRENGTH / Math.min(model.degree[s]!, model.degree[t]!);
    const pull = ((distance - LINK_LENGTH) / distance) * alpha * strength;
    const share = model.degree[s]! / (model.degree[s]! + model.degree[t]!);
    b.vx[t]! -= dx * pull * share;
    b.vy[t]! -= dy * pull * share;
    b.vx[s]! += dx * pull * (1 - share);
    b.vy[s]! += dy * pull * (1 - share);
  }
}

function sortedBy(values: readonly number[]): number[] {
  return values.map((_, i) => i).sort((a, b) => values[a]! - values[b]! || a - b);
}

/** Pairwise repulsion; sorting by x lets the scan stop at CHARGE_RANGE. */
function applyCharge(model: LayoutModel, b: Buffers, alpha: number): void {
  const order = sortedBy(b.xs);
  for (let a = 0; a < order.length; a += 1) {
    const i = order[a]!;
    for (let c = a + 1; c < order.length; c += 1) {
      const j = order[c]!;
      const dx = b.xs[j]! - b.xs[i]!;
      if (dx > CHARGE_RANGE) break;
      const dy = b.ys[j]! - b.ys[i]!;
      const squared = Math.max(dx * dx + dy * dy, 36);
      if (squared > CHARGE_RANGE * CHARGE_RANGE) continue;
      const push = (CHARGE * alpha) / squared;
      b.vx[i]! -= dx * push;
      b.vy[i]! -= dy * push;
      b.vx[j]! += dx * push;
      b.vy[j]! += dy * push;
    }
  }
}

function applyRadial(model: LayoutModel, b: Buffers, alpha: number): void {
  const cx = model.width / 2;
  const cy = model.height / 2;
  model.nodes.forEach((node, i) => {
    if (node.hop === 0) return;
    const ring = ringOf(model, node);
    const ux = (b.xs[i]! - cx) / ring.rx;
    const uy = (b.ys[i]! - cy) / ring.ry;
    const length = Math.hypot(ux, uy) || 1;
    const targetX = cx + (ring.rx * ux) / length;
    const targetY = cy + (ring.ry * uy) / length;
    const home = model.home[i]!;
    b.vx[i]! += (targetX - b.xs[i]!) * RADIAL_STRENGTH * alpha;
    b.vy[i]! += (targetY - b.ys[i]!) * RADIAL_STRENGTH * alpha;
    b.vx[i]! += (home.x - b.xs[i]!) * HOME_STRENGTH * alpha;
    b.vy[i]! += (home.y - b.ys[i]!) * HOME_STRENGTH * alpha;
  });
}

function integrate(model: LayoutModel, b: Buffers): void {
  model.nodes.forEach((node, i) => {
    if (node.hop === 0) {
      b.xs[i] = model.width / 2;
      b.ys[i] = model.height / 2;
      b.vx[i] = 0;
      b.vy[i] = 0;
      return;
    }
    b.vx[i] = b.vx[i]! * VELOCITY_KEEP;
    b.vy[i] = b.vy[i]! * VELOCITY_KEEP;
    b.xs[i] = b.xs[i]! + b.vx[i]!;
    b.ys[i] = b.ys[i]! + b.vy[i]!;
  });
}

function currentBoxes(model: LayoutModel, b: Buffers): Box[] {
  return model.nodes.map((node, i) => {
    const point = { x: b.xs[i]!, y: b.ys[i]! };
    return nodeBox(node, point, labelSide(point, model.width, model.height, node.hop));
  });
}

function shiftBox(box: Box, alongX: boolean, delta: number): void {
  if (alongX) {
    box.x1 += delta;
    box.x2 += delta;
  } else {
    box.y1 += delta;
    box.y2 += delta;
  }
}

/** Pushes two overlapping boxes apart along the axis of least overlap. The
 * anchor never moves; the other node takes the whole push. */
function separate(
  model: LayoutModel,
  b: Buffers,
  boxes: Box[],
  i: number,
  j: number,
  strength: number,
): void {
  const p = boxes[i]!;
  const q = boxes[j]!;
  const overlapX = Math.min(p.x2, q.x2) - Math.max(p.x1, q.x1);
  const overlapY = Math.min(p.y2, q.y2) - Math.max(p.y1, q.y1);
  if (overlapX <= 0 || overlapY <= 0) return;
  const pinnedI = model.nodes[i]!.hop === 0;
  const pinnedJ = model.nodes[j]!.hop === 0;
  const shareI = pinnedI ? 0 : pinnedJ ? 1 : 0.5;
  const alongX = overlapX < overlapY;
  const delta = (alongX ? overlapX : overlapY) * strength;
  const centreGap = alongX ? q.x1 + q.x2 - p.x1 - p.x2 : q.y1 + q.y2 - p.y1 - p.y2;
  const sign = centreGap > 0 || (centreGap === 0 && i < j) ? -1 : 1;
  const moveI = sign * delta * shareI;
  const moveJ = -sign * delta * (1 - shareI);
  const axis = alongX ? b.xs : b.ys;
  axis[i] = axis[i]! + moveI;
  axis[j] = axis[j]! + moveJ;
  shiftBox(p, alongX, moveI);
  shiftBox(q, alongX, moveJ);
}

/** Sweep and prune: boxes sorted by left edge, so each scan stops at the
 * first box that starts right of the current one. */
function applyCollision(model: LayoutModel, b: Buffers, strength: number): void {
  const boxes = currentBoxes(model, b);
  const order = sortedBy(boxes.map((box) => box.x1));
  for (let a = 0; a < order.length; a += 1) {
    const i = order[a]!;
    for (let c = a + 1; c < order.length; c += 1) {
      const j = order[c]!;
      if (boxes[j]!.x1 >= boxes[i]!.x2) break;
      separate(model, b, boxes, i, j, strength);
    }
  }
}

function clampToBounds(model: LayoutModel, b: Buffers): void {
  const boxes = currentBoxes(model, b);
  const right = model.width - EDGE_MARGIN;
  const bottom = model.height - EDGE_MARGIN;
  boxes.forEach((box, i) => {
    if (model.nodes[i]!.hop === 0) return;
    if (box.x1 < EDGE_MARGIN) b.xs[i] = b.xs[i]! + EDGE_MARGIN - box.x1;
    else if (box.x2 > right) b.xs[i] = b.xs[i]! - (box.x2 - right);
    if (box.y1 < EDGE_MARGIN) b.ys[i] = b.ys[i]! + EDGE_MARGIN - box.y1;
    else if (box.y2 > bottom) b.ys[i] = b.ys[i]! - (box.y2 - bottom);
  });
}

export function tickOnce(model: LayoutModel, b: Buffers, tick: number): void {
  const progress = tick / LAYOUT_TICKS;
  const alpha = FORCE_SCALE * (1 - 0.8 * progress * progress);
  applyLinks(model, b, alpha);
  applyCharge(model, b, alpha);
  applyRadial(model, b, alpha);
  integrate(model, b);
  applyCollision(model, b, 0.15 + 0.6 * Math.min(1, progress / 0.4));
  clampToBounds(model, b);
}
