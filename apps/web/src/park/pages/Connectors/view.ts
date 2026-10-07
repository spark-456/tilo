// Connectors page view model: the design's `renderVals` arithmetic as plain functions (Tilo App
// Connectors.dc.html). The page keeps the local overrides (`st`, `lvl`, `synced`); nothing here touches the
// Api and nothing reads a clock: expiry and "Used by" are computed from the data and a `now` the caller passes.
import type { Connector, Skill, World } from "../../api/types";

export const LEVEL_LABEL = ["", "Read", "Draft", "Act"] as const;
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

export const syncLine = (c: Connector): string =>
  c.st === "attention"
    ? (c.sync ?? "")
    : `Synced ${c.sync === "Live" ? "live" : c.sync || "just now"}`;

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
  c.st === "attention"
    ? `${c.sync ?? ""}. Reconnect to keep agents working.`
    : `Healthy · synced ${c.sync === "Live" ? "live" : c.sync || "just now"}`;

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
