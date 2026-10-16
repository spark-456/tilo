import type { TiloMood, TiloRole } from "../../design/tilo-t";
// TILO-T-WORLD: how an agent looks in the chat, the hover card and the panel: a Tilo T Buddy whose role colour follows
// the agent's rank and whose mood follows what its recorded events say it is doing (design/tilo-t PROMPT.md section 3,
// "Moods"). A mood is never a guess: each is picked from the agent's status, which agentStats derives from events.
import type { AgentStatus } from "../../world/agentStats";

const ROLE_OF_RANK: Readonly<Record<string, TiloRole>> = {
  director: "director",
  lead: "delivery",
  specialist: "research",
  writer: "designer",
  verifier: "tester",
  narrator: "finance",
};

export const roleOf = (rank: string): TiloRole => ROLE_OF_RANK[rank] ?? "builder";

/** triggeredBy: agent.working -> work; agent.handoff -> talk (within the talk window); meeting.convened -> listen;
 * the agent's handoff once the window has passed -> happy; before any event -> idle. */
export const MOOD_OF_STATUS: Readonly<Record<AgentStatus, TiloMood>> = {
  working: "work",
  "handing over": "talk",
  "in a meeting": "listen",
  finished: "happy",
  ready: "idle",
  waiting: "idle",
};

/** "m:ss" into the run, from the recorded timestamps (the Story's own clock). */
export function clock(first: string | undefined, ts: string): string {
  const s = Math.max(0, Math.round((Date.parse(ts) - Date.parse(first ?? ts)) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
