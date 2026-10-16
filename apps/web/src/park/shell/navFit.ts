// STUDIO-INT: which nav tabs fit beside the logo and the tools at a given window width (design/studio-v2
// "Tilo S Nav": 72px bar, 32px sides, 28px gaps, 15px/600 tabs with 13px padding). Between the compact page menu
// (below 840px) and the full strip, the tabs that do not fit move into a "More" menu, lowest priority first, so the
// strip never scrolls and the page never scrolls sideways. Pure and width-only: the same width gives the same tabs
// (no measuring, no layout shift after the first frame).
import type { PageId } from "../app/AppCtx";

/** Kept in the strip longest, first to last. */
const PRIORITY: readonly PageId[] = [
  "home",
  "chat",
  "worlds",
  "needs",
  "skills",
  "agenda",
  "team",
  "connectors",
  "ledger",
];

/** A generous width per character of a 15px semibold label, so a label never ends up wider than its estimate. */
const CHAR_PX = 9;
/** 13px a side on a roomy bar, 10px below ROOMY_NAV_FROM (park.shell.css). */
const tabPad = (vw: number): number => (vw >= ROOMY_NAV_FROM ? 26 : 20);
const TAB_GAP_PX = 2;
/** The amber count on Needs you: 8px gap and a 22px pill. */
const BADGE_PX = 30;
/** The More button at its widest: a six-letter page name (it names the current page when that is in the menu),
 * its padding and its chevron. */
const MORE_PX = 6 * CHAR_PX + 20 + 18;
const LOGO_PX = 96;
/** Four 44px tools with 8px gaps; the sample chip adds its label. */
const TOOLS_PX = 208;
const SAMPLE_PX = 128;
/** Room left for rounding, so the last tab never touches the tools. */
const SLACK_PX = 24;
/** At and above this width the bar keeps the artboard's 32px sides and 28px gaps; below, 20px and 16px. */
export const ROOMY_NAV_FROM = 1200;

export function tabWidth(id: PageId, label: string, badge: boolean, vw: number): number {
  return label.length * CHAR_PX + tabPad(vw) + (id === "needs" && badge ? BADGE_PX : 0);
}

/** The width the tab strip may use at window width `vw`. */
export function tabRoom(vw: number, sample: boolean): number {
  const frame = vw >= ROOMY_NAV_FROM ? 32 * 2 + 28 * 2 : 20 * 2 + 16 * 2;
  return vw - frame - LOGO_PX - TOOLS_PX - (sample ? SAMPLE_PX : 0) - SLACK_PX;
}

/** The tabs shown in the strip (in nav order) and the rest (in nav order) for the More menu. `vw` 0 = not measured
 * yet: every tab, as on a wide screen. */
export function fitTabs<T extends readonly [PageId, string]>(
  tabs: readonly T[],
  vw: number,
  opts: { sample: boolean; badge: boolean },
): { shown: T[]; more: T[] } {
  const width = (t: T) => tabWidth(t[0], t[1], opts.badge, vw) + TAB_GAP_PX;
  const room = tabRoom(vw, opts.sample);
  const all = tabs.reduce((sum, t) => sum + width(t), 0);
  if (vw <= 0 || all <= room) return { shown: [...tabs], more: [] };
  const rank = (t: T) => {
    const r = PRIORITY.indexOf(t[0]);
    return r < 0 ? PRIORITY.length : r;
  };
  const keep = new Set<PageId>();
  let used = MORE_PX;
  for (const t of [...tabs].sort((a, b) => rank(a) - rank(b))) {
    if (used + width(t) > room) break;
    used += width(t);
    keep.add(t[0]);
  }
  return {
    shown: tabs.filter((t) => keep.has(t[0])),
    more: tabs.filter((t) => !keep.has(t[0])),
  };
}
