// What the World page works out from the data before it draws (design: "Tilo App World.dc.html", renderVals).
// Pure functions of the Api's worlds, decisions, skills and connectors; no scenario literal lives here.
import type { Connector, Dec, Decision, Skill, World, WorldState } from "../../api/types";

/** A state's look: label, chip fill, chip text, dot colour, bar colour. */
export type StateLook = readonly [
  label: string,
  chipBg: string,
  chipFg: string,
  dot: string,
  bar: string,
];

const NEEDS_FILL = "#F0A500";
const NEEDS_INK = "#1F1D2B";

const STATES: Record<WorldState, StateLook> = {
  needs: ["Needs you", NEEDS_FILL, NEEDS_INK, NEEDS_INK, "var(--amber)"],
  running: ["Running", "var(--chip)", "var(--ink)", "var(--run)", "var(--run)"],
  scheduled: ["Scheduled", "var(--chip)", "var(--ink)", "var(--sch)", "var(--sch)"],
  finished: ["Ready", "var(--okSoft)", "var(--okInk)", "var(--ok)", "var(--ok)"],
};
const PAUSED: StateLook = ["Paused", "var(--chip)", "var(--ink)", "var(--ink3)", "var(--ink3)"];
const STARTING: StateLook = [
  "Starting",
  "var(--heroSoft)",
  "var(--heroInk)",
  "var(--hero)",
  "var(--hero)",
];

/** The look of the world's status chip and progress bar: paused wins, then a new world, then its state. */
export const stateLook = (w: World, paused: boolean): StateLook =>
  paused ? PAUSED : w.isNew ? STARTING : STATES[w.st];

/**
 * UI-10 B2 (HR-1): only a world with agents on it can be paused. A finished or scheduled world has nothing running,
 * so "Paused · agents are waiting" would describe agents that do not exist.
 */
export const canPause = (w: World): boolean => w.st === "running" || w.st === "needs";

/**
 * UI-10 B2: a world whose data is a recorded sample (fixture or demo session) carries a state with no event behind it
 * now. The page says so instead of presenting "Running" or a countdown as live.
 */
export const isRecordedRunning = (w: World, real: boolean): boolean =>
  !real && w.st === "running" && !w.isNew;

/** A running line of a recorded world: the recorded words behind a plain label, never a live countdown. */
export const recordedLine = (line: string): string => `Recorded sample state: ${line}`;

/** A district's chip: label, chip fill, chip text, tile fill, tile icon colour, bar colour. */
export type DistrictLook = readonly [
  label: string,
  chipBg: string,
  chipFg: string,
  tile: string,
  tileInk: string,
  bar: string,
];
export const DISTRICT_LOOK: Record<WorldState, DistrictLook> = {
  needs: [
    "Needs you",
    NEEDS_FILL,
    NEEDS_INK,
    "var(--amberTile)",
    "var(--amberInk)",
    "var(--amber)",
  ],
  running: [
    "Building",
    "var(--heroSoft)",
    "var(--heroInk)",
    "var(--heroSoft)",
    "var(--heroInk)",
    "var(--run)",
  ],
  finished: ["Done", "var(--okSoft)", "var(--okInk)", "var(--okSoft)", "var(--ok)", "var(--ok)"],
  scheduled: ["Planned", "var(--chip)", "var(--ink2)", "var(--sunk)", "var(--ink2)", "var(--sch)"],
};

/** The map legend, in the design's order. */
export const LEGEND: readonly (readonly [colour: string, label: string])[] = [
  ["var(--run)", "Building"],
  ["var(--amber)", "Needs you"],
  ["var(--ok)", "Done"],
  ["var(--track)", "Planned"],
];

export const ACTIVITY_DOT = {
  needs: "var(--amber)",
  done: "var(--ok)",
  info: "var(--run)",
} as const;

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;
export const decisionsWord = (n: number): string => plural(n, "decision", "decisions");
export const agentsWord = (n: number): string => plural(n, "agent", "agents");

/** Share of the budget spent, 0..100 (a world over budget fills the bar and stops). */
export const spendShare = (w: World): number =>
  w.budget ? Math.min(100, (w.spendV / w.budget) * 100) : 0;

/** The line under the hero map: the world's own tag, else one derived from its tier. */
export function heroTagOf(w: World): string {
  if (w.heroTag) return w.heroTag;
  if (w.tier === "City") return `${w.districts?.length ?? 0} districts · ${w.agents} agents`;
  if (w.tier === "Town") {
    return w.tool === "Routine"
      ? `Runs on a schedule · ${w.nextL} ${w.nextV}`
      : `Small project · ${w.agents} agents`;
  }
  return `Quick task · ${agentsWord(w.agents)}`;
}

/** The note under the spend bar: a decision's own note, else the tier's line. */
export function spendNoteOf(w: World, mine: readonly Decision[], dec: Dec): string {
  const noted = mine.find((d) => d.facts?.spendNote);
  if (noted?.facts?.spendNote) {
    return dec[noted.k] ? noted.facts.spendNote.decided : noted.facts.spendNote.waiting;
  }
  if (w.tier === "Town") return `Each run costs about ${w.spend}. Billed monthly.`;
  if (w.budget) return `${Math.round(spendShare(w))}% of budget used. Forecast within budget.`;
  return "Quick tasks are billed when they finish.";
}

// A skill names a tool the connectors list calls something else.
const CONNECTOR_OF_TOOL: Record<string, string | null> = {
  "Google Sheets": "gdrive",
  "Google Workspace": "gmail",
  Web: null,
  BambooHR: "bamboo",
};
const FALLBACK_TOOLS = ["Gmail", "Google Drive"];

export interface ToolChip {
  readonly name: string;
  readonly mono: string;
  readonly colour: string;
}

/** The skills that ran in this world and the tools they use (a world with no skill lists the two defaults). */
export function skillsAndTools(
  w: World,
  skills: readonly Skill[],
  connectors: readonly Connector[],
): { skills: Skill[]; tools: ToolChip[] } {
  const used = skills.filter((s) => s.used.includes(w.id));
  const names: string[] = [];
  for (const s of used) for (const t of s.tools) if (!names.includes(t[0])) names.push(t[0]);
  if (names.length === 0) names.push(...FALLBACK_TOOLS);
  const tools = names.map((name) => {
    const link = CONNECTOR_OF_TOOL[name];
    const c =
      connectors.find((x) => x.name === name) ??
      (link ? connectors.find((x) => x.id === link) : undefined);
    return {
      name,
      mono: name === "Web" ? "W" : c ? c.mono : (name[0] ?? ""),
      colour: c ? c.col : "var(--ink2)",
    };
  });
  return { skills: used, tools };
}

/** Keys for rows that may repeat their text (two runs "today"): the text, then its count so far. */
export function keyed<T>(items: readonly T[], text: (item: T) => string): [string, T][] {
  const seen = new Map<string, number>();
  return items.map((item) => {
    const base = text(item);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return [n === 0 ? base : `${base}#${n}`, item];
  });
}
