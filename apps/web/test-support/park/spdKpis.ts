// FR-SPD-01 / FR-SPD-07 test support (supplement 1.3): reads the five KPI tiles by their public text, and states
// the figure each tile must show as a pure function of the ledger object the page was given. Nothing here is
// bundled. Tiles are found by label text only (no class names, no test ids), so Ledger and Home can share the
// markup or not.
import type { Ledger } from "../../src/park/api/types";

export const KPI_LABELS = [
  "Spent so far",
  "Month-end forecast",
  "Waiting on you",
  "Saved by memory",
  "Hours handed back",
] as const;
export type KpiLabel = (typeof KPI_LABELS)[number];

/** A tile is a short block (label, value, sub). The longest tile text allowed, so a whole card never counts. */
const MAX_TILE_TEXT = 110;

const text = (el: Element): string => el.textContent ?? "";

/**
 * Every element that could be the tile of `label`: climb from each deepest element holding the label while the
 * parent holds none of the other four labels. Case-sensitive, so the lowercase "waiting on you" in a spend note
 * is not a label. More than one candidate is normal (a card heading may repeat a label); callers look for one
 * whose text carries the expected figure.
 */
export function tileCandidates(root: ParentNode, label: KpiLabel): HTMLElement[] {
  const others = KPI_LABELS.filter((l) => l !== label);
  const all = [...root.querySelectorAll<HTMLElement>("*")];
  const holders = all.filter(
    (el) => text(el).includes(label) && ![...el.children].some((c) => text(c).includes(label)),
  );
  const out: HTMLElement[] = [];
  for (const h of holders) {
    let tile: HTMLElement = h;
    let p = h.parentElement;
    while (p && root.contains(p) && !others.some((o) => text(p as HTMLElement).includes(o))) {
      tile = p;
      p = p.parentElement;
    }
    if (text(tile).length <= MAX_TILE_TEXT && !out.includes(tile)) out.push(tile);
  }
  return out;
}

/** The tile of `label` whose text contains `figure`, or undefined. */
export const tileShowing = (
  root: ParentNode,
  label: KpiLabel,
  figure: string,
): HTMLElement | undefined => tileCandidates(root, label).find((t) => text(t).includes(figure));

/** Every label that has at least one tile-shaped block. */
export const tileLabelsPresent = (root: ParentNode): KpiLabel[] =>
  KPI_LABELS.filter((l) => tileCandidates(root, l).length > 0);

/** The control a person presses for a tile: the tile itself, a control around it, or one inside it. */
export function controlOf(tile: HTMLElement): HTMLElement | undefined {
  const sel = 'button, a, [role="button"], [role="link"]';
  return tile.closest<HTMLElement>(sel) ?? tile.querySelector<HTMLElement>(sel) ?? undefined;
}

// ---- the figures, derived from the ledger object itself ----

/** Whole units with a thousands separator (the ledger's own display rule for amounts of 100 or more). */
const amount = (v: number): string => Math.round(v).toLocaleString("en-GB");
export const pounds = (v: number): string => `£${amount(v)}`;
export const dollars = (v: number): string => `$${amount(v)}`;

const sum = (xs: readonly number[]): number => xs.reduce((a, v) => a + v, 0);

/** What the tiles must show for a ledger that is waiting on one transaction and has not decided it yet. */
export function figuresOf(
  L: Ledger,
  fmt: (v: number) => string = pounds,
): Record<KpiLabel, string> {
  const waiting = L.tx.filter((t) => t.st === "waiting").reduce((a, t) => a + t.amt, 0);
  return {
    "Spent so far": fmt(L.spent),
    "Month-end forecast": fmt(L.forecast),
    "Waiting on you": fmt(waiting),
    "Saved by memory": fmt(sum(L.memory)),
    "Hours handed back": `${sum(L.hours.map((h) => h[1]))} h`,
  };
}

/** The same ledger with every KPI source changed, to figures the fixture does not contain anywhere. */
export function variedLedger(base: Ledger): Ledger {
  const L = structuredClone(base);
  L.spent = 3100;
  L.forecast = 7200;
  const waiting = L.tx.find((t) => t.st === "waiting");
  if (waiting) waiting.amt = 910;
  L.memory = [10, 20, 30, 40];
  L.hours = [
    ["Finance", 5, "var(--ok)", "Invoice matching"],
    ["Operations", 4, "var(--hero)", "Rota"],
  ];
  return L;
}
