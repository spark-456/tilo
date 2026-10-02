// AGW-05 S-06: the queue follows the run's recorded events (PRD 9.4 HR-1, PRD 10.2/10.3). Each
// case plays a prefix of the village stream (or a few synthetic events), so the moments between
// events are tested exactly, not by timing.
import type { Event } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { CARDS_VALID } from "../api/fixtures/cards";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { deriveQueue, rungOf } from "./queue";

const upTo = (seq: number): Event[] => EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= seq);
const base = EVENTS_VILLAGE_BASIC[0] as Event;
// The contract fixtures reuse ids across cards, so each case picks its card by what it is.
const must = <T>(v: T | undefined): T => {
  if (v === undefined) throw new Error("fixture card missing");
  return v;
};
const gateCard = must(CARDS_VALID.find((c) => c.gate?.id === "G1"));
const questionCard = must(CARDS_VALID.find((c) => c.rung === "needs_you"));
const SECOND = "01JB5VQ0000000000000009003";

/** An event of the card's own run, so the card belongs to it. */
const ev = (seq: number, type: string, data: object, over: Partial<Event> = {}): Event => ({
  ...base,
  id: `01JB5VQ00000000000000099${String(seq).padStart(2, "0")}`,
  seq,
  type,
  run_id: gateCard.run_id,
  summary: `${type} ${seq}`,
  cause: null,
  data,
  ...over,
});
const requested = (seq: number, cardId = gateCard.id, gateId = "G1") =>
  ev(seq, "approval.requested", { gate_id: gateId, card_id: cardId });
const resolved = (seq: number, cardId = gateCard.id, gateId = "G1") =>
  ev(seq, "approval.resolved", { gate_id: gateId, card_id: cardId, option: "hold" });
const routed = (seq: number) =>
  ev(
    seq,
    "question.routed",
    { card_id: questionCard.id, domain: null },
    { actor: "A_s1", target: "u_owner" },
  );
const answered = (seq: number, over: Partial<Event> = {}) =>
  ev(
    seq,
    "question.answered",
    { answered_by: "person" },
    { actor: "u_owner", target: "A_s1", ...over },
  );

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
    const events = [requested(1), resolved(2, "01JB5VQ0000000000000009009")];
    expect(deriveQueue(events)).toEqual([]);
  });
});

describe("PRD-18.3 AGW-05 S-06 a question waits from question.routed until question.answered", () => {
  it("opens on the route and closes on an answer that names its agent", () => {
    expect(deriveQueue([routed(1)]).map((i) => i.kind)).toEqual(["question"]);
    expect(deriveQueue([routed(1), answered(2)])).toEqual([]);
  });
  it("closes on an answer whose cause is the routed event, whoever asked", () => {
    const r = routed(1);
    expect(deriveQueue([r, answered(2, { target: "A_other", cause: r.id })])).toEqual([]);
  });
  it("closes nothing for an answer that names neither the event nor the asking agent", () => {
    expect(deriveQueue([routed(1), answered(2, { target: "A_other" })])).toHaveLength(1);
  });
  it("keeps the other open card when one closes, in the order they opened", () => {
    const events = [requested(1), routed(2), requested(3, SECOND, "G2"), resolved(4)];
    expect(deriveQueue(events).map((i) => i.cardId)).toEqual([questionCard.id, SECOND]);
  });
});

describe("PRD-18.3 AGW-05 S-06 only a card of this run is joined to an item", () => {
  it("joins the card with the same id and run id", () => {
    expect(deriveQueue([requested(1)], [gateCard])[0]?.card).toBe(gateCard);
  });
  it("never joins a card of another run, even with the same id", () => {
    expect(
      deriveQueue([requested(1)], [{ ...gateCard, run_id: "r_other_run" }])[0]?.card,
    ).toBeNull();
  });
  it("lists no card the events did not open: the contract cards of the village run stay out", () => {
    expect(deriveQueue(upTo(44), CARDS_VALID)).toEqual([]);
    expect(deriveQueue(upTo(34), CARDS_VALID)[0]?.card).toBeNull(); // card 9001 is not a fixture card
  });
  it("ignores events of other types, and an unregistered one", () => {
    const unknown = ev(2, "queue.invented", { card_id: gateCard.id });
    expect(deriveQueue([requested(1), unknown, ev(3, "agent.working", {})])).toHaveLength(1);
  });
});
