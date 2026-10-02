// AGW-05 S-06: the queue follows the run's recorded events (PRD 9.4 HR-1, PRD 10.2/10.3). Each
// case plays a prefix of the village stream (or a few events built from the contract fixtures), so
// the moments between events are tested exactly, not by timing.
import type { Event } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import {
  GATE_REPLY,
  QUESTION,
  RUN_A,
  RUN_B,
  answered,
  policyApplied,
  requested,
  resolved,
  routed,
} from "../../test-support/needsYou";
import { CARDS_VALID } from "../api/fixtures/cards";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { deriveQueue, rungOf } from "./queue";

const upTo = (seq: number): Event[] => EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= seq);
const SECOND = "01JB5VQ0000000000000009003";

describe("PRD-18.3 AGW-05 S-06 the queue follows approval.requested and approval.resolved", () => {
  const waiting = (seq: number) => deriveQueue(upTo(seq)).length;
  it("is 0 before seq 34, 1 from the request until the answer, 0 after", () => {
    expect([33, 34, 36, 37, 44].map(waiting)).toEqual([0, 1, 1, 0, 0]);
  });
  it("names the gate and the card the request opened", () => {
    const [item] = deriveQueue(upTo(34));
    expect(item?.kind).toBe("gate");
    expect(item?.gateId).toBe("G1");
    expect(item?.cardId).toBe("01JB5VQ0000000000000009001");
    expect(item && rungOf(item)).toEqual({ label: "Approval gate", tone: "gate" });
  });
  it("closes a gate on the answer for its gate id even when the card id differs", () => {
    const events = [requested(1), resolved(2, "hold", "01JB5VQ0000000000000009009")];
    expect(deriveQueue(events)).toEqual([]);
  });
  it("orders by seq, whatever order the events arrive in", () => {
    expect(deriveQueue([upTo(37)[36] as Event, upTo(34)[33] as Event])).toEqual([]);
    expect(deriveQueue([requested(5, SECOND, "G2"), requested(1)]).map((i) => i.cardId)).toEqual([
      GATE_REPLY.id,
      SECOND,
    ]);
  });
  it("does not throw on an event whose data is null", () => {
    const broken = { ...requested(2), data: null } as unknown as Event;
    expect(deriveQueue([requested(1), broken])).toHaveLength(1);
  });
});

describe("PRD-18.3 AGW-05 S-06 a gate closes only for an authorised, valid decision", () => {
  it("keeps a gate waiting when approval.resolved names a bad option or carries the wrong authz", () => {
    expect(deriveQueue([requested(1), resolved(2, "maybe")])).toHaveLength(1);
    expect(
      deriveQueue([
        requested(1),
        resolved(2, "approve", GATE_REPLY.id, "G1", RUN_A, { authz: null }),
      ]),
    ).toHaveLength(1);
    const byPolicy = {
      authz: { by: "policy" as const, ref: "pol_x", at: "2026-09-29T09:32:09.500Z" },
    };
    expect(
      deriveQueue([requested(1), resolved(2, "approve", GATE_REPLY.id, "G1", RUN_A, byPolicy)]),
    ).toHaveLength(1);
  });
  it("closes a gate for a Team Lead's answer", () => {
    const lead = {
      authz: { by: "team_lead" as const, ref: "u_lead", at: "2026-09-29T09:32:09.500Z" },
    };
    expect(
      deriveQueue([requested(1), resolved(2, "hold", GATE_REPLY.id, "G1", RUN_A, lead)]),
    ).toEqual([]);
  });
  it("treats a gate a policy opened as closed, and ignores policy.applied without a policy authz", () => {
    expect(deriveQueue([requested(1), policyApplied(2)])).toEqual([]);
    expect(
      deriveQueue([requested(1), policyApplied(2, "G1", RUN_A, { authz: null })]),
    ).toHaveLength(1);
  });
});

describe("PRD-18.3 AGW-05 S-06 two runs of one world never touch each other's state", () => {
  it("run A's answer for G1 does not close run B's waiting G1", () => {
    const events = [requested(1), requested(2, SECOND, "G1", RUN_B), resolved(3, "approve")];
    const items = deriveQueue(events);
    expect(items.map((i) => [i.runId, i.gateId])).toEqual([[RUN_B, "G1"]]);
  });
  it("run A's policy.applied for G1 does not close run B's waiting G1", () => {
    const events = [requested(1, SECOND, "G1", RUN_B), policyApplied(2, "G1", RUN_A)];
    expect(deriveQueue(events)).toHaveLength(1);
  });
  it("an answer in run A does not close the same agent's question in run B", () => {
    const events = [
      routed(1, QUESTION.id, "A_s1", RUN_A),
      routed(2, SECOND, "A_s1", RUN_B),
      answered(3, "A_s1", RUN_A),
    ];
    expect(deriveQueue(events).map((i) => i.runId)).toEqual([RUN_B]);
  });
});

describe("PRD-18.3 AGW-05 S-06 a question waits from question.routed until question.answered", () => {
  it("opens on the route and closes on an answer that names its agent", () => {
    expect(deriveQueue([routed(1)]).map((i) => i.kind)).toEqual(["question"]);
    expect(deriveQueue([routed(1), answered(2)])).toEqual([]);
  });
  it("closes on an answer whose cause is the routed event, whoever asked", () => {
    const r = routed(1);
    expect(deriveQueue([r, answered(2, "A_other", RUN_A, { cause: r.id })])).toEqual([]);
  });
  it("closes nothing for an answer that names neither the event nor the asking agent", () => {
    expect(deriveQueue([routed(1), answered(2, "A_other")])).toHaveLength(1);
  });
  it("closes nothing when two questions of the asking agent wait and the answer names neither", () => {
    expect(deriveQueue([routed(1), routed(2, SECOND), answered(3)])).toHaveLength(2);
  });
  it("keeps the other open card when one closes, in the order they opened", () => {
    const events = [requested(1), routed(2), requested(3, SECOND, "G2"), resolved(4, "hold")];
    expect(deriveQueue(events).map((i) => i.cardId)).toEqual([QUESTION.id, SECOND]);
  });
});

describe("PRD-18.3 AGW-05 S-06 only a card of this run is joined to an item", () => {
  it("joins the card with the same id and run id", () => {
    expect(deriveQueue([requested(1)], [GATE_REPLY])[0]?.card).toBe(GATE_REPLY);
  });
  it("never joins a card of another run, even with the same id", () => {
    expect(deriveQueue([requested(1)], [{ ...GATE_REPLY, run_id: RUN_B }])[0]?.card).toBeNull();
  });
  it("lists no card the events did not open: the contract cards of the village run stay out", () => {
    expect(deriveQueue(upTo(44), CARDS_VALID)).toEqual([]);
    expect(deriveQueue(upTo(34), CARDS_VALID)[0]?.card).toBeNull(); // card 9001 is not a fixture card
  });
  it("ignores events of other types, and an unregistered one", () => {
    const unknown = { ...requested(2), type: "queue.invented" };
    expect(
      deriveQueue([requested(1), unknown, { ...requested(3), type: "agent.working" }]),
    ).toHaveLength(1);
  });
});
