/**
 * TILO-T-WORLD step 2 (HR-1): every agent line is a speech bubble with the event's real words when it is recorded:
 * a handoff note, a Lead's assignment, a help request and a question routed to the person (shown "To You").
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { reduce } from "./reducer";

const layout = villageBasicLayout() as unknown as Layout;

let n = 0;
function ev(
  type: string,
  actor: string,
  target: string,
  summary: string,
  data: object = {},
): Event {
  n += 1;
  return {
    v: "1.0",
    id: `01JB5VQ${String(n).padStart(19, "0")}`,
    seq: n,
    ts: "2026-10-16T09:00:00.000Z",
    world_id: "w",
    run_id: "r",
    type,
    actor,
    target,
    level: "L1",
    district: "D1",
    item: null,
    severity: "info",
    credits: 0,
    summary,
    cause: null,
    vis: "all",
    authz: null,
    data,
    trace: {},
  } as unknown as Event;
}

const placed = (): Event[] => {
  n = 0;
  return [
    ev("agent.spawned", "A_dir", "A_l1", "x"),
    ev("agent.moved", "A_l1", "B1", "x", { from: "B1" }),
    ev("agent.spawned", "A_l1", "A_s1", "x"),
  ];
};

const said = (events: Event[], id: string) =>
  frameOf(layout, reduce(layout, events)).agents.find((a) => a.id === id)?.say;

test("FR-WLD-04 TILO-T-WORLD says: a help request is a bubble with the agent's real line, to the Lead", () => {
  const events = [
    ...placed(),
    ev("agent.help_requested", "A_s1", "A_l1", "Which thread should I reply in?"),
  ];
  expect(said(events, "A_s1")).toEqual({ text: "Which thread should I reply in?", to: "Lead" });
});

test("FR-WLD-04 TILO-T-WORLD says: a question routed to the person is a bubble to You, with its real words", () => {
  const events = [...placed(), ev("question.routed", "A_l1", "u_owner", "Should I cc finance?")];
  expect(said(events, "A_l1")).toEqual({ text: "Should I cc finance?", to: "You" });
});

test("FR-WLD-04 TILO-T-WORLD says: the bubble ends with the agent's next event, as a handoff note does", () => {
  const events = [
    ...placed(),
    ev("question.routed", "A_l1", "u_owner", "Should I cc finance?"),
    ev("agent.moved", "A_l1", "B2", "x", { from: "B1" }),
  ];
  expect(said(events, "A_l1")).toBeNull();
});
