// The `app` prop every Park page receives (design_handoff_tilo_web_app README "The `app` prop";
// plan section 10). Pages get this object and nothing else from the shell: no router, no store.
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
  "settings",
  "library",
  "more",
  "chat",
] as const;

export type PageId = (typeof PAGE_IDS)[number];
export type Params = Record<string, string>;
export type Motion = "lively" | "calm" | "still";

/** The page name the shell shows in the title and the Placeholder. */
export const PAGE_LABEL: Record<PageId, string> = {
  home: "Home",
  worlds: "Worlds",
  world: "World",
  skills: "Skills",
  ledger: "Ledger",
  agenda: "Agenda",
  team: "Team",
  profile: "Profile",
  connectors: "Connectors",
  settings: "Settings",
  library: "Library",
  more: "More",
  chat: "Chat",
};

export interface AppCtx {
  page: PageId;
  params: Params;
  go: (page: PageId, params?: Params) => void;
  dec: Dec;
  decide: (key: DecisionKey, text?: string, option?: string) => void;
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
