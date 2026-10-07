// Connectors page view model: the design's `renderVals` arithmetic as plain functions (Tilo App
// Connectors.dc.html). The page keeps the local overrides (`st`, `lvl`); nothing here touches the Api.
import type { Connector } from "../../api/types";

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

export type Overrides = {
  st: Record<string, Connector["st"]>;
  lvl: Record<string, number>;
};

export interface Merged extends Connector {
  level: number;
}

/** The fixture connectors with the page's own connect, disconnect and level choices applied. */
export function merge(list: Connector[], o: Overrides): Merged[] {
  return list.map((c) => {
    const st = o.st[c.id];
    const sync = st ? "just now" : c.sync;
    return {
      ...c,
      st: st ?? c.st,
      ...(sync === undefined ? {} : { sync }),
      level: o.lvl[c.id] ?? (c.level || 1),
    };
  });
}

export const isOn = (c: Connector): boolean => c.st === "connected" || c.st === "attention";

export const matches = (c: Connector, q: string): boolean =>
  !q || `${c.name} ${c.cat}`.toLowerCase().includes(q.toLowerCase());

export const syncLine = (c: Connector): string =>
  c.st === "attention"
    ? (c.sync ?? "")
    : `Synced ${c.sync === "Live" ? "live" : c.sync || "just now"}`;

export const usedLine = (c: Connector): string =>
  c.used?.length ? `Used by ${c.used.length}` : "Not used yet";

/** The attention banner's two lines, built from the connector record (its sync text, first skill and scope). */
export function bannerText(c: Connector): { title: string; sub: string } {
  const sync = c.sync ?? "";
  const skill = c.used?.[0];
  const scope = c.scopes?.[0]?.[0].replace(/^Read /, "");
  return {
    title: `${c.name} ${sync.charAt(0).toLowerCase()}${sync.slice(1)}`,
    sub: `${skill && scope ? `${skill} reads ${scope} from it. ` : ""}Reconnect to keep it running.`,
  };
}

export const drawerSync = (c: Connector): string =>
  c.st === "attention"
    ? `${c.sync ?? ""}. Reconnect to keep agents working.`
    : `Healthy · synced ${c.sync === "Live" ? "live" : c.sync || "just now"}`;
