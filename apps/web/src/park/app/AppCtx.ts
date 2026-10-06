// THROWAWAY (WEB-3b validation only): stand-in for the WEB-3a AppCtx.
import type { Dec, DecisionKey, TierKey, World } from "../api/types";

export const PAGE_IDS = [
  "home",
  "worlds",
  "world",
  "skills",
  "ledger",
  "agenda",
  "team",
  "profile",
  "connectors",
] as const;
export type PageId = (typeof PAGE_IDS)[number];
export type Params = Record<string, string>;
export type Motion = "lively" | "calm" | "still";

export interface AppCtx {
  page: PageId;
  params: Params;
  go: (page: PageId, params?: Params) => void;
  dec: Dec;
  decide: (key: DecisionKey) => void;
  needsLeft: number;
  added: World[];
  addWorld: (mode: TierKey, query: string) => World;
  toast: (msg: string, actionLabel?: string, action?: () => void) => void;
  time: "day" | "night";
  night: boolean;
  motion: Motion;
  setPref: (key: string, value: unknown) => void;
  prefs: Record<string, unknown>;
  vw: number;
  vh: number;
  pins: { x: number; y: number }[];
  ready: boolean;
}
