// FR-UX-13: the world the composer shows for a task the server accepted (`POST /intake`). Only what the reply
// served carries a value: the id is the server's `task_id`, the name comes from the brief's goal (else the
// words the person typed), the tier from the size they chose. The task is not approved yet and has no events, so
// it is "scheduled" with a plain waiting line, never "running" (HR-1..HR-7). Never imports the fixtures.
import type { TierKey, TierName, World } from "../types";

const TIER_OF: Readonly<Record<TierKey, TierName>> = {
  quick: "Village",
  routine: "Town",
  workspace: "City",
};

export interface IntakeReply {
  task_id: string;
  brief: { goal?: string };
}

export function worldFromIntake(mode: TierKey, reply: IntakeReply, typed: string): World {
  const name = reply.brief.goal?.trim() || typed.trim() || "New task";
  return {
    id: reply.task_id,
    name,
    short: name.length > 26 ? `${name.slice(0, 24)}…` : name,
    tier: TIER_OF[mode],
    tool: "",
    st: "scheduled",
    isNew: true,
    agents: 0,
    spend: "",
    spendV: 0,
    nextL: "Status",
    nextV: "Waiting for your approval",
    owner: "",
    started: "",
  };
}
