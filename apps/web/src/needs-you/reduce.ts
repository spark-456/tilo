// The one reducer behind the Needs-you queue (S-06) and the gate sheet (S-07), so the two never
// disagree about an event (PRD 10.2, 10.4; HR-1, HR-5, HR-7). It reads recorded events in seq order
// and keys everything by run: a plan-local gate id (G1) or agent id repeats across the runs of one
// world, so an event only ever acts on the state its own run opened. A gate opens only with the
// authz the registry allows for its event: approval.resolved by a person or a Team Lead,
// policy.applied by a policy; anything else changes nothing, so the gate stays as it was.
import type { Event } from "@tilo/contracts";

export type GateOption = "approve" | "edit" | "hold";

export type GateOutcome =
  | { readonly state: "waiting" }
  | {
      readonly state: "decided";
      readonly option: GateOption;
      readonly by: "person" | "team_lead";
      readonly event: Event;
    }
  | { readonly state: "policy"; readonly event: Event };

export interface GateRecord {
  readonly gateId: string;
  readonly runId: string;
  /** The card the request named; a policy-opened gate has none (policy.applied has no card). */
  readonly cardId: string | null;
  /** approval.requested, or null for a gate only a decision or a policy touched. */
  readonly requested: Event | null;
  readonly outcome: GateOutcome;
}

export interface QuestionRecord {
  readonly cardId: string;
  /** question.routed: the event that opened it. */
  readonly opened: Event;
}

/** A string field of the event's data, or null: a schema-invalid event never throws here. */
export const field = (e: Event, key: string): string | null => {
  const v = (e.data as Record<string, unknown> | null)?.[key];
  return typeof v === "string" ? v : null;
};

/** A number field of the event's data, or null. */
export const numField = (e: Event, key: string): number | null => {
  const v = (e.data as Record<string, unknown> | null)?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
};

/** The unique id of a gate across runs. */
export const gateKey = (runId: string, gateId: string): string => `${runId}/${gateId}`;

export function reduceNeedsYou(events: readonly Event[]): {
  gates: GateRecord[];
  questions: QuestionRecord[];
} {
  const gates = new Map<string, GateRecord>();
  const questions = new Map<string, QuestionRecord>();
  for (const e of [...events].sort((a, b) => a.seq - b.seq)) {
    const gateId = field(e, "gate_id");
    const key = gateId ? gateKey(e.run_id, gateId) : null;
    const old = key ? gates.get(key) : undefined;
    if (e.type === "approval.requested" && key && gateId) {
      // A new request resets its gate: a redraft is a new proposal (outbox rules OB-01, OB-05).
      gates.set(key, {
        gateId,
        runId: e.run_id,
        cardId: field(e, "card_id"),
        requested: e,
        outcome: { state: "waiting" },
      });
    } else if (e.type === "approval.resolved" && key && gateId) {
      const option = field(e, "option");
      const by = e.authz?.by;
      if (option !== "approve" && option !== "edit" && option !== "hold") continue;
      if (by !== "person" && by !== "team_lead") continue; // registry: authz_by [person, team_lead]
      gates.set(key, {
        gateId,
        runId: e.run_id,
        cardId: old?.cardId ?? field(e, "card_id"),
        requested: old?.requested ?? null,
        outcome: { state: "decided", option, by, event: e },
      });
    } else if (e.type === "policy.applied" && key && gateId) {
      if (e.authz?.by !== "policy") continue; // registry: authz_by [policy]
      gates.set(key, {
        gateId,
        runId: e.run_id,
        cardId: old?.cardId ?? null,
        requested: old?.requested ?? null,
        outcome: { state: "policy", event: e },
      });
    } else if (e.type === "question.routed") {
      const cardId = field(e, "card_id");
      if (cardId) questions.set(gateKey(e.run_id, cardId), { cardId, opened: e });
    } else if (e.type === "question.answered") {
      // The answer names its question by `cause`; failing that, by the agent that asked (its
      // `target`) within the same run, and only when exactly one question of that agent waits:
      // a guess could close the wrong card.
      const inRun = [...questions.entries()].filter(([, q]) => q.opened.run_id === e.run_id);
      const byCause = inRun.filter(([, q]) => e.cause !== null && q.opened.id === e.cause);
      const byAgent = inRun.filter(([, q]) => q.opened.actor === e.target);
      const hit = byCause.length === 1 ? byCause : byAgent.length === 1 ? byAgent : [];
      for (const [k] of hit) questions.delete(k);
    }
  }
  return { gates: [...gates.values()], questions: [...questions.values()] };
}
