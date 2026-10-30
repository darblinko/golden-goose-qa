"use client";

import { type RefObject, useEffect, useRef, useState } from "react";
import {
  LAYOUT_TICKS,
  type LayoutEdge,
  type LayoutNode,
  type Point,
  computeTraceLayout,
  createLayout,
  layoutPositions,
  stepLayout,
} from "@/lib/traceLayout";

const SETTLE_MS = 1200;
const MAX_TICKS_PER_FRAME = 6;

export interface Size {
  width: number;
  height: number;
}

export function useElementSize(ref: RefObject<HTMLElement | null>): Size | null {
  const [size, setSize] = useState<Size | null>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const width = Math.floor(entry.contentRect.width);
      const height = Math.floor(entry.contentRect.height);
      setSize((current) =>
        current && current.width === width && current.height === height
          ? current
          : { width, height },
      );
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Positions for the current graph. A new graph animates from the anchor
 * outwards over SETTLE_MS; a resize or reduced motion jumps to the settled
 * layout. The settled positions are the same either way. */
export function useTraceLayout(
  nodes: readonly LayoutNode[],
  edges: readonly LayoutEdge[],
  size: Size | null,
  seed: number,
): Map<string, Point> | null {
  const [positions, setPositions] = useState<Map<string, Point> | null>(null);
  const animatedNodes = useRef<readonly LayoutNode[] | null>(null);

  useEffect(() => {
    if (!size || size.width < 80 || size.height < 80 || nodes.length === 0) {
      setPositions(null);
      return;
    }
    const isNewGraph = animatedNodes.current !== nodes;
    animatedNodes.current = nodes;
    if (!isNewGraph || prefersReducedMotion()) {
      setPositions(computeTraceLayout(nodes, edges, size.width, size.height, seed));
      return;
    }
    let state = createLayout(nodes, edges, size.width, size.height, seed);
    setPositions(layoutPositions(state));
    // The clock starts at the first frame and each frame advances a bounded
    // number of ticks, so a busy main thread delays the motion but never skips it.
    let start: number | null = null;
    const advance = (now: number) => {
      start ??= now;
      const due = Math.ceil(((now - start) / SETTLE_MS) * LAYOUT_TICKS);
      const ticks = Math.min(due - state.tick, MAX_TICKS_PER_FRAME);
      state = stepLayout(state, Math.max(ticks, 1));
      setPositions(layoutPositions(state));
      if (state.tick < LAYOUT_TICKS) frame = requestAnimationFrame(advance);
    };
    let frame = requestAnimationFrame(advance);
    return () => {
      cancelAnimationFrame(frame);
      // An interrupted animation replays on the next run instead of jumping.
      if (state.tick < LAYOUT_TICKS) animatedNodes.current = null;
    };
  }, [nodes, edges, size, seed]);

  return positions;
}
