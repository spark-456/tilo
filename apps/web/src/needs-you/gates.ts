// What happened at each gate of a run, from its recorded events alone (HR-1, HR-5, HR-7): a gate
// waits from approval.requested, a person (or a Team Lead) answers it with approval.resolved, or
// the policy engine opens it with policy.applied. Nothing here says a gate is open until one of
// those events says so; only "approve" opens a gate (card rule CR-07).
import type { Authz, Event } from "@tilo/contracts";

export type GateOption = "approve" | "edit" | "hold";

export type GateOutcome =
  | { readonly state: "waiting" }
  | {
      readonly state: "decided";
      readonly option: GateOption;
      readonly by: Authz["by"] | null;
      readonly event: Event;
    }
  | { readonly state: "policy"; readonly event: Event };

export interface GateRecord {
  readonly gateId: string;
  /** The card the request named; a policy-opened gate has none (policy.applied has no card). */
  readonly cardId: string | null;
  readonly runId: string;
  /** approval.requested, or null for a gate only a policy opened. */
  readonly requested: Event | null;
  readonly outcome: GateOutcome;
}

const text = (e: Event, key: string): string | null => {
  const v = (e.data as Record<string, unknown>)[key];
  return typeof v === "string" ? v : null;
};

/** One record per gate, in the order the gates first appeared. A new request resets its gate. */
export function gatesOf(events: readonly Event[]): GateRecord[] {
  const gates = new Map<string, GateRecord>();
  for (const e of events) {
    const gateId = text(e, "gate_id");
    if (!gateId) continue;
    const old = gates.get(gateId);
    if (e.type === "approval.requested") {
      gates.set(gateId, {
        gateId,
        cardId: text(e, "card_id"),
        runId: e.run_id,
        requested: e,
        outcome: { state: "waiting" },
      });
    } else if (e.type === "approval.resolved") {
      const option = text(e, "option");
      if (option !== "approve" && option !== "edit" && option !== "hold") continue;
      gates.set(gateId, {
        gateId,
        cardId: old?.cardId ?? text(e, "card_id"),
        runId: e.run_id,
        requested: old?.requested ?? null,
        outcome: { state: "decided", option, by: e.authz?.by ?? null, event: e },
      });
    } else if (e.type === "policy.applied") {
      gates.set(gateId, {
        gateId,
        cardId: old?.cardId ?? null,
        runId: e.run_id,
        requested: old?.requested ?? null,
        outcome: { state: "policy", event: e },
      });
    }
  }
  return [...gates.values()];
}

/** The gate is open: a person approved it, or a policy opened it. Hold and Edit first keep it shut. */
export const isOpen = (g: GateRecord): boolean =>
  g.outcome.state === "policy" || (g.outcome.state === "decided" && g.outcome.option === "approve");

/** "pol_autopilot_l2" -> "Autopilot L2": no event carries a policy's own name, so its id is read
 * as words (open question on #84; the Autonomy log names it the same way). */
export const policyName = (id: string): string =>
  id
    .replace(/^pol_/, "")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase())
    .replace(/\b([a-z])(\d)\b/g, (_m, l: string, d: string) => `${l.toUpperCase()}${d}`);

/** PRD 18.4 policy copy: who authorised it and how to undo. */
export const policyLine = (verb: string, name: string, undoS: number): string =>
  `${verb} under your rule '${name}'. Undo within ${undoS} s.`;

/** What was done, as the policy line says it ("Sent under your rule ..."). */
export const DONE: Readonly<Record<string, string>> = {
  send_email: "Sent",
  send_message: "Sent",
  save_file: "Saved",
};
