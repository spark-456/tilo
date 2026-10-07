// WIRE-2: tilo-api `GET /worlds` items (S-14) as Park worlds. Only the served fields carry values; everything the
// API does not serve is empty or zero, never a sample (HR-1..HR-7). Defaults: BQ-WIRE2-1..3.
import type { World, WorldState } from "../types";

export type WorldListStatus = "idle" | "started" | "paused" | "completed" | "failed";

export interface WorldListItem {
  world_id: string;
  title: string | null;
  status: WorldListStatus;
  created_at: string | null;
  last_seq: number;
}

/** `needs` comes only from a recorded open card and `running` only from `world.started`/`resumed` (BQ-WIRE2-2). */
export const STATE_OF: Readonly<Record<WorldListStatus, WorldState>> = {
  idle: "scheduled",
  started: "running",
  paused: "scheduled",
  completed: "finished",
  failed: "finished",
};

const UNTITLED = "Untitled world";

function worldOf(item: WorldListItem): World {
  const name = item.title || UNTITLED;
  return {
    id: item.world_id,
    name,
    short: name,
    tier: "Village",
    tool: "",
    st: STATE_OF[item.status],
    agents: 0,
    spend: "",
    spendV: 0,
    nextL: "",
    nextV: "",
    owner: "",
    started: item.created_at ?? "",
  };
}

export function worldsFromList(items: readonly WorldListItem[]): World[] {
  return items.map(worldOf);
}
