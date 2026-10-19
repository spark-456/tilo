/**
 * WORLD-LIVE (FR-WLD-04, HR-1..HR-6): what the live events make the world show. A worker spawned by a Lead who has a
 * post stands there until it is sent; agent.working shows a tool icon; agent.handoff shows the real short note as a
 * speech bubble that names the receiver; either clears at that agent's next event. Nothing here is a timer: every
 * bubble and icon is in the frame only because a recorded event put it in the state.
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { applyEvent, createInitialState, reduce } from "./reducer";

const layout = villageBasicLayout() as unknown as Layout;

let n = 0;
function ev(type: string, actor: string, target: string, data: object = {}, summary = "x"): Event {
  n += 1;
  return {
    v: "1.0",
    id: `01JB5VQ${String(n).padStart(19, "0")}`,
    seq: n,
    ts: "2026-10-16T09:00:00.000Z",
    world_id: "w_live",
    run_id: "r_live",
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

const post = (): Event[] => {
  n = 0;
  return [
    ev("agent.spawned", "system", "A_dir", { role: "director" }),
    ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
    ev("agent.moved", "A_l1", "B1", { from: "B1" }),
  ];
};

test("FR-WLD-04 WORLD-LIVE: an agent spawned by a Lead who has a post stands at that post", () => {
  const events = [...post(), ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" })];
  const state = reduce(layout, events);
  expect(state.agents.A_l1?.location).toBe("B1");
  expect(state.agents.A_s1?.location).toBe("B1");
  expect(frameOf(layout, state).agents.map((a) => a.id)).toContain("A_s1");
});

test("FR-WLD-04 WORLD-LIVE: an agent spawned by someone with no post is not placed until an event places it", () => {
  n = 0;
  const state = reduce(layout, [
    ev("agent.spawned", "system", "A_dir", { role: "director" }),
    ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
  ]);
  expect(state.agents.A_l1?.location).toBeNull();
});

test("FR-WLD-04 WORLD-LIVE: agent.working shows the tool icon until the agent's next event", () => {
  const base = [...post(), ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" })];
  const working = reduce(layout, [...base, ev("agent.working", "A_s1", "B2", { unit: "U1" })]);
  expect(frameOf(layout, working).agents.find((a) => a.id === "A_s1")?.working).toBe(true);
  expect(frameOf(layout, working).agents.find((a) => a.id === "A_l1")?.working).toBe(false);
  const moved = reduce(layout, [
    ...base,
    ev("agent.working", "A_s1", "B2", { unit: "U1" }),
    ev("agent.moved", "A_s1", "B1", { from: "B2" }),
  ]);
  expect(frameOf(layout, moved).agents.find((a) => a.id === "A_s1")?.working).toBe(false);
});

const envelope = (summary: string) => ({
  envelope: {
    from: "A_s1",
    to: "A_l1",
    artifact_refs: [],
    summary,
    acceptance_criteria: ["done"],
    provenance_ids: [],
  },
});

test("FR-WLD-04 WORLD-LIVE: agent.handoff shows the real note as a bubble naming the receiver", () => {
  const events = [
    ...post(),
    ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
    ev("agent.working", "A_s1", "B2", { unit: "U1" }),
    ev(
      "agent.handoff",
      "A_s1",
      "A_l1",
      envelope("Found three flights under budget."),
      "ignored line",
    ),
  ];
  const agent = frameOf(layout, reduce(layout, events)).agents.find((a) => a.id === "A_s1");
  expect(agent?.say).toEqual({ text: "Found three flights under budget.", to: "Lead" });
  expect(agent?.working).toBe(false); // it handed over: the tool is down
});

test("FR-WLD-04 WORLD-LIVE: a handoff with no envelope note falls back to the event's own summary, capped", () => {
  const long = "w".repeat(300);
  const events = [
    ...post(),
    ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
    ev("agent.handoff", "A_s1", "A_l1", {}, long),
  ];
  const say = frameOf(layout, reduce(layout, events)).agents.find((a) => a.id === "A_s1")?.say;
  expect(say?.text.length).toBeLessThanOrEqual(140);
});

test("FR-WLD-04 WORLD-LIVE: the bubble goes when the speaker's next event arrives or it retires", () => {
  const base = [
    ...post(),
    ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
    ev("agent.handoff", "A_s1", "A_l1", envelope("Done.")),
  ];
  const said = (events: Event[]) =>
    frameOf(layout, reduce(layout, events)).agents.find((a) => a.id === "A_s1")?.say;
  expect(said(base)).not.toBeNull();
  expect(said([...base, ev("agent.retired", "A_l1", "A_s1")])).toBeNull();
  expect(said([...base, ev("agent.moved", "A_s1", "B2", { from: "B1" })])).toBeNull();
});

test("FR-WLD-04 WORLD-LIVE: agent.assigned shows what the Lead gave, as the Lead's own bubble", () => {
  const events = [
    ...post(),
    ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
    ev("agent.assigned", "A_l1", "A_s1", { unit: "U1" }, "The Lead gave it: Find flights"),
  ];
  const lead = frameOf(layout, reduce(layout, events)).agents.find((a) => a.id === "A_l1");
  expect(lead?.say).toEqual({ text: "The Lead gave it: Find flights", to: "Specialist 1" });
});

// A copy of the layout whose B3 is the Meeting Hall (the live layout has one; the fixture's Town Hall stands in).
const hallLayout = (() => {
  const copy = structuredClone(layout) as unknown as {
    semantic: { levels: { districts: { buildings: { id: string; common_type?: string }[] }[] }[] };
  };
  const b3 = copy.semantic.levels[0]?.districts[0]?.buildings.find((b) => b.id === "B3");
  if (b3) b3.common_type = "meeting_hall";
  return copy as unknown as Layout;
})();
const convened = (agents: string[]) =>
  ev("meeting.convened", "A_owner", "A_l1", {
    room_id: "01JB5VQ0000000000000000R01",
    lead: "A_l1",
    agents,
    as_role: "owner",
    run_state: "live",
    credit_cap: 5,
    max_turns: 10,
  });

test("FR-WLD-04 WORLD-LIVE: meeting.convened takes the called agents to the Meeting Hall and adjourned sends them back", () => {
  const base = [...post(), ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" })];
  const room = [...base, convened(["A_s1"])];
  const at = (events: Event[], id: string) => reduce(hallLayout, events).agents[id]?.location;
  expect(at(room, "A_l1")).toBe("B3");
  expect(at(room, "A_s1")).toBe("B3");
  expect(at(room, "A_dir")).not.toBe("B3"); // not called
  const closed = [
    ...room,
    ev("meeting.adjourned", "A_owner", "A_l1", {
      room_id: "01JB5VQ0000000000000000R01",
      reason: "person",
      turns: 0,
      credits_spent: 0,
    }),
  ];
  expect(at(closed, "A_l1")).toBe("B1");
  expect(at(closed, "A_s1")).toBe("B1");
});

test("FR-WLD-04 WORLD-LIVE: with no Meeting Hall in the layout a convened room moves nobody", () => {
  const base = [...post(), ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" })];
  const state = reduce(layout, [...base, convened(["A_s1"])]);
  expect(state.agents.A_l1?.location).toBe("B1");
  expect(state.rooms).toEqual({});
});

test("FR-WLD-04 WORLD-LIVE: buildings rise planned -> constructing -> operational -> completed, one event each", () => {
  const events = [
    ...post(),
    ev("building.planned", "A_dir", "B2", { plan_units: ["U1"] }),
    ev("building.constructing", "A_l1", "B2", { unit: "U1" }),
    ev("building.operational", "A_l1", "B2", { unit: "U1" }),
    ev("building.completed", "A_l1", "B2", { unit_type: "research", unit_count: 1 }),
  ];
  const statusAfter = (k: number) => {
    let s = createInitialState(layout);
    for (const e of events.slice(0, k)) s = applyEvent(s, e, layout);
    return frameOf(layout, s).buildings.find((b) => b.id === "B2")?.status;
  };
  expect(statusAfter(3)).toBeUndefined(); // nothing is drawn until building.planned
  expect([statusAfter(4), statusAfter(5), statusAfter(6), statusAfter(7)]).toEqual([
    "planned",
    "constructing",
    "operational",
    "completed",
  ]);
});
