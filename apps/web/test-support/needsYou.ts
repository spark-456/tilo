// Test-only helpers for the AGW-05 Needs-you tests (not shipped app code). Every event is built from
// its contract fixture in contracts/fixtures/events/valid, so it carries every required field
// (outbox_id, item, approver, team_lead, authz ...); a test only names what it varies. `liveClient`
// is a client whose events and answers the test controls one by one.
import fs from "node:fs";
import path from "node:path";
import type { Card, Event } from "@tilo/contracts";
import { act } from "react";
import type { CardAnswer } from "../src/api/client";
import { FixtureClient } from "../src/api/fixtureClient";
import { CARDS_VALID } from "../src/api/fixtures/cards";
import { CONTRACTS_DIR } from "./worldFixtures";

/** The contract fixtures reuse ids across cards, so each case picks its card by what it is. */
export function must<T>(v: T | undefined): T {
  if (v === undefined) throw new Error("fixture missing");
  return v;
}
export const GATE_REPLY: Card = must(CARDS_VALID.find((c) => c.gate?.id === "G1"));
export const GATE_SAVE: Card = must(CARDS_VALID.find((c) => c.gate?.id === "G2"));
export const QUESTION: Card = must(CARDS_VALID.find((c) => c.rung === "needs_you"));

/** Two runs of one world: the cards belong to RUN_A; RUN_B reuses its plan-local ids (G1, A_s1). */
export const RUN_A = GATE_REPLY.run_id;
export const RUN_B = "r_01J8Z3K4M6";

const fixture = (name: string): Event =>
  JSON.parse(
    fs.readFileSync(
      path.join(CONTRACTS_DIR, "fixtures", "events", "valid", `${name}.json`),
      "utf8",
    ),
  ) as Event;

const build = (
  name: string,
  seq: number,
  run: string,
  data: object,
  over: Partial<Event> = {},
): Event => {
  const base = fixture(name);
  return {
    ...base,
    id: `01JB5VQ00000000000000099${String(seq).padStart(2, "0")}`,
    seq,
    run_id: run,
    cause: null,
    ...over,
    data: { ...(base.data as object), ...data },
  };
};

export const requested = (
  seq: number,
  cardId = GATE_REPLY.id,
  gateId = "G1",
  run = RUN_A,
  data: object = {},
) => build("approval.requested", seq, run, { gate_id: gateId, card_id: cardId, ...data });
export const resolved = (
  seq: number,
  option: string,
  cardId = GATE_REPLY.id,
  gateId = "G1",
  run = RUN_A,
  over: Partial<Event> = {},
) => build("approval.resolved", seq, run, { gate_id: gateId, card_id: cardId, option }, over);
export const policyApplied = (
  seq: number,
  gateId = "G1",
  run = RUN_A,
  over: Partial<Event> = {},
  data: object = {},
) => build("policy.applied", seq, run, { gate_id: gateId, ...data }, over);
export const routed = (seq: number, cardId = QUESTION.id, actor = "A_s1", run = RUN_A) =>
  build("question.routed", seq, run, { card_id: cardId }, { actor });
export const answered = (seq: number, target = "A_s1", run = RUN_A, over: Partial<Event> = {}) =>
  build("question.answered", seq, run, {}, { target, ...over });

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
