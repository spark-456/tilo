// Connectors page view model: the design's `renderVals` arithmetic as plain functions (Tilo App
// Connectors.dc.html). The page keeps the local overrides (`st`, `lvl`); nothing here touches the Api.
import type { Connector } from "../../api/types";

export const LEVEL_LABEL = ["", "Read", "Draft", "Act"] as const;
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

export const drawerSync = (c: Connector): string =>
  c.st === "attention"
    ? `${c.sync ?? ""}. Reconnect to keep agents working.`
    : `Healthy · synced ${c.sync === "Live" ? "live" : c.sync || "just now"}`;
