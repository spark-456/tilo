// WEB-PARITY: optional per-page regions for the per-region diffs. A page with no entry here is
// compared as a 3x3 grid. Each page ticket adds its own entries once both sides have stable markup:
//   team: [{ name: "header", design: "[data-screen-label='Team'] > div:first-child", ours: "[data-park] h1" }],
//   ledger: [{ name: "kpis", x: 0, y: 120, w: 1440, h: 220 }],
import type { Rect } from "./diff";

/** A named region, found by a selector on each side, or one fixed rect (page pixels) on both. */
export type RegionSpec = { name: string; design: string; ours: string } | ({ name: string } & Rect);

/** Style-only root for a page without REGIONS: the design's page card and ours (WEB-3a: adjust to the real markup). */
export const DEFAULT_STYLE_ROOT: RegionSpec = {
  name: "page",
  design: "[data-screen-label]",
  ours: "[data-park] [data-screen-label]",
};

export const REGIONS: Record<string, RegionSpec[]> = {};
