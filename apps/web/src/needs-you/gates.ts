// What happened at each gate of a run, from its recorded events alone (HR-1, HR-5, HR-7), by the
// reducer the queue also uses (reduce.ts): a gate waits from approval.requested, a person or a Team
// Lead answers it with approval.resolved, or the policy engine opens it with policy.applied. Only
// "approve" opens a gate (card rule CR-07). Nothing says a gate is open until an event does.
import type { Event } from "@tilo/contracts";
import { type GateRecord, reduceNeedsYou } from "./reduce";

export type { GateOption, GateOutcome, GateRecord } from "./reduce";

/** One record per gate and run, in the order the gates first appeared. */
export const gatesOf = (events: readonly Event[]): GateRecord[] => reduceNeedsYou(events).gates;

/** Who opened the gate: the authz of the event that did, or "none" while it is waiting or shut. */
export function openedBy(g: GateRecord): "person" | "team_lead" | "policy" | "none" {
  const o = g.outcome;
  if (o.state === "policy") return "policy";
  return o.state === "decided" && o.option === "approve" ? o.by : "none";
}

/** The gate is open: a person approved it, or a policy opened it. Hold and Edit first keep it shut. */
export const isOpen = (g: GateRecord): boolean => openedBy(g) !== "none";

/** "pol_autopilot_l2" -> "Autopilot L2": no event carries a policy's own name, so its id is read
 * as words (open question on #84; the Autonomy log names it the same way). */
export const policyName = (id: string): string =>
  id
    .replace(/^pol_/, "")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase())
    .replace(/\b([a-z])(\d)\b/g, (_m, l: string, d: string) => `${l.toUpperCase()}${d}`);

/** PRD 18.4 policy copy: who authorised it and how to undo. A part the event did not record is
 * left out, never printed as "undefined". */
export const policyLine = (verb: string, name: string | null, undoS: number | null): string =>
  `${verb} under your rule${name ? ` '${name}'` : ""}.${undoS === null ? "" : ` Undo within ${undoS} s.`}`;

/** What was done, as the policy line says it ("Sent under your rule ..."). */
export const DONE: Readonly<Record<string, string>> = {
  send_email: "Sent",
  send_message: "Sent",
  save_file: "Saved",
};
