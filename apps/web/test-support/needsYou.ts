// Test-only helpers for the AGW-05 Needs-you tests (not shipped app code): a synthetic event of a
// card's own run, and a client whose events and answers the test controls one by one.
import type { Card, Event } from "@tilo/contracts";
import { act } from "react";
import type { CardAnswer } from "../src/api/client";
import { FixtureClient } from "../src/api/fixtureClient";
import { CARDS_VALID } from "../src/api/fixtures/cards";
import { EVENTS_VILLAGE_BASIC } from "../src/api/fixtures/events";

/** The contract fixtures reuse ids across cards, so each case picks its card by what it is. */
export function must<T>(v: T | undefined): T {
  if (v === undefined) throw new Error("fixture missing");
  return v;
}
export const GATE_REPLY: Card = must(CARDS_VALID.find((c) => c.gate?.id === "G1"));
export const GATE_SAVE: Card = must(CARDS_VALID.find((c) => c.gate?.id === "G2"));
export const QUESTION: Card = must(CARDS_VALID.find((c) => c.rung === "needs_you"));

const base = must(EVENTS_VILLAGE_BASIC[0]);
/** An event of the gate card's run, so the cards of that run belong to it. */
export const ev = (seq: number, type: string, data: object, over: Partial<Event> = {}): Event => ({
  ...base,
  id: `01JB5VQ00000000000000099${String(seq).padStart(2, "0")}`,
  seq,
  type,
  run_id: GATE_REPLY.run_id,
  summary: `${type} ${seq}`,
  cause: null,
  data,
  ...over,
});

const person = { by: "person", ref: "u_owner", at: "2026-09-29T09:32:09.500Z" } as const;
export const requested = (seq: number, card: Card = GATE_REPLY) =>
  ev(seq, "approval.requested", {
    gate_id: card.gate?.id,
    card_id: card.id,
    action_type: card.gate?.action.type,
    risk_tier: card.gate?.risk_tier,
    irreversible: card.gate?.irreversible,
  });
export const resolved = (seq: number, option: string, card: Card = GATE_REPLY) =>
  ev(
    seq,
    "approval.resolved",
    { gate_id: card.gate?.id, card_id: card.id, option, channel: "web", pin_verified: false },
    { authz: person },
  );

/** A client whose events arrive when the test pushes them, and which records every answer. */
export function liveClient(cards: readonly Card[]) {
  const sent: Array<readonly [string, CardAnswer]> = [];
  let deliver: (e: Event) => void = () => undefined;
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    deliver = onEvent;
    return () => undefined;
  };
  client.listCards = async () => [...cards];
  client.answerCard = async (id, answer) => {
    sent.push([id, answer]);
  };
  return {
    client,
    sent,
    push: (e: Event) => act(async () => deliver(e)),
  };
}
