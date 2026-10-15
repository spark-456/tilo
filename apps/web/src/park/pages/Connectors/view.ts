// Connectors page view model: the design's `renderVals` arithmetic as plain functions (Tilo App
// Connectors.dc.html). The page keeps the local overrides (`st`, `lvl`, `synced`); nothing here touches the
// Api and nothing reads a clock: expiry and "Used by" are computed from the data and a `now` the caller passes.
import type { Connector, Skill, World } from "../../api/types";

export const LEVEL_LABEL = ["Off", "Read", "Draft", "Act"] as const;

/** FR-ACC-01 / BQ-DSN-04: what each level is meant to let agents do, as a ceiling on the risk tier. Plain-language
 * line on sample data; the mapping lives in tilo_policy.access_levels, which no connector call enforces yet. */
const CEILING = [
  "Off blocks every call to this tool.",
  "Read allows read-only actions (T0).",
  "Draft allows drafts and internal staging (T0 to T1), never an external send.",
  "Act goes no further than the policy engine allows (T2 within policy). T3 actions always need an approval card.",
] as const;
export const ceilingOf = (level: number): string => CEILING[level] ?? CEILING[0];

/** A skill's level can only restrict the team's level, never raise it (FR-ACC-02): the lower of the two. */
export const effectiveLevel = (team: number, skill: number | undefined): number =>
  skill === undefined ? team : Math.min(team, skill);
export const DEFAULT_SCOPES: [string, number][] = [
  ["Read", 1],
  ["Draft", 2],
  ["Act", 3],
];

/** FR-ACC-04: the sign-in warning starts this many days before the sign-in lapses. */
export const WARN_DAYS = 3;
const DAY_MS = 86_400_000;

export type Overrides = {
  st: Record<string, Connector["st"]>;
  lvl: Record<string, number>;
  /** Connectors whose "Sync now" has finished in this visit. */
  synced?: Record<string, true>;
};

export interface Merged extends Connector {
  level: number;
  /** Set when the warning comes from `expires`: "soon" within WARN_DAYS, "expired" once it has passed. */
  exp?: "soon" | "expired";
}

export type Expiry = { state: "ok" } | { state: "soon"; days: number } | { state: "expired" };

/** Where a sign-in stands at `nowMs`: whole days left are rounded up, and exactly WARN_DAYS still warns. */
export function expiryOf(c: Connector, nowMs: number): Expiry {
  const at = c.expires ? Date.parse(c.expires) : Number.NaN;
  if (Number.isNaN(at)) return { state: "ok" };
  const left = at - nowMs;
  if (left <= 0) return { state: "expired" };
  if (left > WARN_DAYS * DAY_MS) return { state: "ok" };
  return { state: "soon", days: Math.ceil(left / DAY_MS) };
}

const expiryText = (e: Exclude<Expiry, { state: "ok" }>): string =>
  e.state === "expired"
    ? "Sign-in expired"
    : `Sign-in expires in ${e.days} ${e.days === 1 ? "day" : "days"}`;

export const isOn = (c: Connector): boolean => c.st === "connected" || c.st === "attention";

/**
 * The fixture connectors with the page's own connect, disconnect and level choices applied. With `nowMs`, a
 * connected tool whose `expires` is within WARN_DAYS (or past) moves to attention with the matching sync text.
 */
export function merge(list: Connector[], o: Overrides, nowMs?: number): Merged[] {
  return list.map((c) => {
    const st = o.st[c.id];
    const e = nowMs === undefined || st || !isOn(c) ? undefined : expiryOf(c, nowMs);
    const flagged = e && e.state !== "ok" ? e : undefined;
    const base: Connector = flagged ? { ...c, st: "attention", sync: expiryText(flagged) } : c;
    const settled = st || (o.synced?.[c.id] && base.st !== "attention");
    const sync = settled ? "just now" : base.sync;
    return {
      ...base,
      st: st ?? base.st,
      ...(sync === undefined ? {} : { sync }),
      level: o.lvl[c.id] ?? (c.level || 1),
      ...(flagged ? { exp: flagged.state } : {}),
    };
  });
}

export const matches = (c: Connector, q: string): boolean =>
  !q || `${c.name} ${c.cat}`.toLowerCase().includes(q.toLowerCase());

/**
 * POLISH-2 (design "Tilo S Connectors" category chips): the chip a tool's own `cat` falls under. Only the sample list
 * carries `cat`; the live registry (GET /v1/connectors) has no category, so the live page shows no chips.
 */
export const CATEGORY_CHIPS = ["Email", "Files", "Calendar", "Meetings", "Build", "Other"] as const;
export type CategoryChip = (typeof CATEGORY_CHIPS)[number];
export function chipOf(cat: string): CategoryChip {
  const c = cat.toLowerCase();
  if (c.includes("email")) return "Email";
  if (c.includes("calendar")) return "Calendar";
  if (c.includes("meeting")) return "Meetings";
  if (/(files?|docs?)/.test(c)) return "Files";
  if (/(code|projects?|build)/.test(c)) return "Build";
  return "Other";
}

/**
 * HR-1: this list is the sample company's, so no sync event stands behind a tool's "synced 2 min ago" or "synced
 * live". A connected tool says so plainly; only the sign-in warning (worked out from `expires`) keeps its text.
 */
export const SAMPLE_STRIP =
  "Not synced: no sign-in or health check has run on these. Sign in to use your own tools.";
export const SAMPLE_DRAWER_LINE = "Example only · no sync or health check recorded";

/** One line per tile: the sign-in warning, else the plain state. The "not synced" note is said once, in SAMPLE_STRIP. */
export const syncLine = (c: Connector): string =>
  c.st === "attention" ? (c.sync ?? "") : "Connected";

export const usedLine = (c: Connector): string =>
  c.used?.length ? `Used by ${c.used.length}` : "Not used yet";

/** The attention banner's two lines, built from the connector record (its sync text, first skill and scope). */
export function bannerText(c: Merged): { title: string; sub: string } {
  const sync = c.sync ?? "";
  const skill = c.used?.[0];
  const scope = c.scopes?.[0]?.[0].replace(/^Read /, "");
  const tail =
    c.exp === "expired" ? "Reconnect to start it again." : "Reconnect to keep it running.";
  return {
    title: `${c.name} ${sync.charAt(0).toLowerCase()}${sync.slice(1)}`,
    sub: `${skill && scope ? `${skill} reads ${scope} from it. ` : ""}${tail}`,
  };
}

export const drawerSync = (c: Connector): string =>
  c.st === "attention" ? `${c.sync ?? ""}. Reconnect to keep agents working.` : SAMPLE_DRAWER_LINE;

/** A "Used by" row: a skill or world that touches the tool (linked by id), or another place the record names. */
export interface UsedRow {
  name: string;
  kind: "skill" | "world" | "other";
  id?: string;
}

/**
 * FR-ACC-03: what touches the tool. The connector's own record comes first, then every skill whose `tools`
 * names it, then the worlds those skills run in (`Skill.used` holds world ids). Nothing is listed by hand.
 */
export function usedBy(
  c: Connector,
  skills: readonly Skill[],
  worlds: readonly World[],
): UsedRow[] {
  const rows: UsedRow[] = [];
  const seen = new Set<string>();
  const add = (row: UsedRow) => {
    const key = `${row.kind}:${row.name}`;
    if (seen.has(key)) return;
    seen.add(key);
    rows.push(row);
  };
  const touching: Skill[] = [];
  for (const name of c.used ?? []) {
    const s = skills.find((k) => k.name === name);
    add(s ? { name, kind: "skill", id: s.id } : { name, kind: "other" });
    if (s) touching.push(s);
  }
  const tool = c.name.toLowerCase();
  for (const s of skills) {
    if (!s.tools.some(([t]) => t.toLowerCase() === tool)) continue;
    add({ name: s.name, kind: "skill", id: s.id });
    if (!touching.includes(s)) touching.push(s);
  }
  for (const s of touching) {
    for (const wid of s.used) {
      const w = worlds.find((x) => x.id === wid);
      if (w) add({ name: w.name, kind: "world", id: w.id });
    }
  }
  return rows;
}
