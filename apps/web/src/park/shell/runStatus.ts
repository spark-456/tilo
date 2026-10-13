// RUN-INDICATOR (PRD 9.4 HR-1, HR-2): what the bottom run bar says, as a pure function of the worlds the Api
// served. A world is `running` only from a recorded start (the live list maps `world.started`/`resumed` to it) and
// stops at a recorded end; `needs` is a recorded open card (the run is held). Nothing here reads `prog`, counts
// time or invents a step: no percentage, no estimate.
import type { World } from "../api/types";

export interface RunBarState {
  /** "running" moves (a ring); "held" is static text. */
  kind: "running" | "held";
  label: string;
  /** The latest recorded activity line of a single running world, else its name, else a count of worlds. */
  detail: string | null;
}

export const HELD_LABEL = "Waiting for your approval";

const worldsText = (n: number): string => `${n} worlds`;

/** The bar for these worlds, or null when nothing is running and nothing is held. */
export function runBarOf(worlds: readonly World[]): RunBarState | null {
  const running = worlds.filter((w) => w.st === "running");
  if (running.length > 0) {
    const agents = running.reduce((n, w) => n + Math.max(0, w.agents), 0);
    const only = running.length === 1 ? running[0] : undefined;
    return {
      kind: "running",
      label: agents > 0 ? `${agents} ${agents === 1 ? "agent" : "agents"} working` : "Working",
      detail: only ? (only.activity?.[0]?.text ?? only.short) : worldsText(running.length),
    };
  }
  const held = worlds.filter((w) => w.st === "needs");
  if (held.length > 0) {
    const only = held.length === 1 ? held[0] : undefined;
    return { kind: "held", label: HELD_LABEL, detail: only ? only.short : worldsText(held.length) };
  }
  return null;
}
