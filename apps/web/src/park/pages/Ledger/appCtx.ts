// The shell -> page contract (README "The app prop"). TEMPORARY local copy: park/app/AppCtx.ts arrives
// with WEB-3a (AG-WEB), and this file is then replaced by `import type { AppCtx } from "../../app/AppCtx"`.
import type { DecisionKey, TierKey, World } from "../../api/types";

export type PageId =
  | "home"
  | "worlds"
  | "world"
  | "skills"
  | "ledger"
  | "agenda"
  | "team"
  | "profile"
  | "connectors";

export interface AppCtx {
  page: PageId;
  params: Record<string, string>;
  go(page: PageId, params?: Record<string, string>): void;
  dec: Partial<Record<DecisionKey, boolean>>;
  decide(key: DecisionKey): void;
  needsLeft: number;
  added: World[];
  addWorld(mode: TierKey, query: string): World;
  toast(msg: string, actionLabel?: string, action?: () => void): void;
  time: "day" | "night";
  night: boolean;
  motion: "lively" | "calm" | "still";
  setPref(key: string, value: unknown): void;
  prefs: Record<string, unknown>;
  vw: number;
  vh: number;
  pins: { x: number; y: number }[];
  ready: boolean;
}
