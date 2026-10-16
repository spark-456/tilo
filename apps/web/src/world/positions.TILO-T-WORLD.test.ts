/**
 * TILO-T-WORLD step 1 (FR-WLD-04, HR-1): agents never huddle. Every place an agent stands has an event basis: a Lead
 * at its recorded post, a worker at the building an agent.working / agent.moved put it at, a finished world with each
 * agent beside the building it worked on, and idle agents fanned out with offsets that never change.
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { TALK_WINDOW, applyEvent, createInitialState, reduce, standingAt } from "./reducer";

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

/** The harness's real order for one unit: spawn, assign, walk to the site, work, walk back, hand over. */
function unit(worker: string, site: string, home = "B1"): Event[] {
  return [
    ev("agent.spawned", "A_l1", worker, { role: "specialist" }),
    ev("agent.assigned", "A_l1", worker, { unit: "U1" }),
    ev("agent.moved", worker, site, { from: home }),
    ev("agent.working", worker, site, { unit: "U1" }),
    ev("agent.moved", worker, home, { from: site }),
    ev("agent.handoff", worker, "A_l1", { envelope: { summary: "Done" } }),
  ];
}

const start = (): Event[] => {
  n = 0;
  return [
    ev("agent.spawned", "system", "A_dir", { role: "director" }),
    ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
    ev("agent.moved", "A_l1", "B1", { from: "B1" }),
    ev("agent.moved", "A_dir", "B1", { from: "B1" }),
  ];
};

const chatter = (count: number): Event[] =>
  Array.from({ length: count }, () => ev("artifact.created", "A_l1", "art_x"));

test("FR-WLD-04 TILO-T-WORLD: a worker's post is the building its agent.working put it at, not the Lead's desk", () => {
  const state = reduce(layout, [...start(), ...unit("A_s1", "B2")]);
  expect(state.agents.A_s1?.post).toBe("B2");
  expect(state.agents.A_l1?.post).toBe("B1");
});

test("FR-WLD-04 TILO-T-WORLD: the handing-over worker stands beside its Lead while the talk window is open", () => {
  const state = reduce(layout, [...start(), ...unit("A_s1", "B2")]);
  expect(standingAt(state, state.agents.A_s1 as never)).toBe("B1");
});

test("FR-WLD-04 TILO-T-WORLD: a finished worker goes back to the building it worked on after the window", () => {
  const state = reduce(layout, [...start(), ...unit("A_s1", "B2"), ...chatter(TALK_WINDOW + 1)]);
  expect(standingAt(state, state.agents.A_s1 as never)).toBe("B2");
  expect(standingAt(state, state.agents.A_l1 as never)).toBe("B1");
});

test("FR-WLD-04 TILO-T-WORLD: a finished world has no two units' workers in one place", () => {
  const events = [
    ...start(),
    ...unit("A_s1", "B2"),
    ...unit("A_s2", "B3"),
    ...unit("A_v1", "B5"),
    ...chatter(TALK_WINDOW + 1),
  ];
  const state = reduce(layout, events);
  const frame = frameOf(layout, state);
  const workers = frame.agents.filter((a) => a.rank !== "lead" && a.rank !== "director");
  expect(workers).toHaveLength(3);
  const spots = new Set(workers.map((a) => `${a.cx.toFixed(1)},${a.cy.toFixed(1)}`));
  expect(spots.size).toBe(3);
  const lead = frame.agents.find((a) => a.rank === "lead");
  for (const w of workers)
    expect(Math.hypot(w.cx - (lead?.cx ?? 0), w.cy - (lead?.cy ?? 0))).toBeGreaterThan(20);
});

test("FR-WLD-04 TILO-T-WORLD: workers that share a building are fanned out and stay put when another arrives", () => {
  const first = reduce(layout, [...start(), ...unit("A_s1", "B2"), ...chatter(TALK_WINDOW + 1)]);
  const second = reduce(layout, [
    ...start(),
    ...unit("A_s1", "B2"),
    ...unit("A_s2", "B2"),
    ...chatter(TALK_WINDOW + 1),
  ]);
  const at = (s: typeof first, id: string) => frameOf(layout, s).agents.find((a) => a.id === id);
  expect(at(second, "A_s1")?.cx).toBe(at(first, "A_s1")?.cx);
  expect(at(second, "A_s1")?.cy).toBe(at(first, "A_s1")?.cy);
  const gap = Math.hypot(
    (at(second, "A_s1")?.cx ?? 0) - (at(second, "A_s2")?.cx ?? 0),
    (at(second, "A_s1")?.cy ?? 0) - (at(second, "A_s2")?.cy ?? 0),
  );
  expect(gap).toBeGreaterThan(14);
});

test("FR-WLD-04 TILO-T-WORLD: an agent with no recorded work stands where its last event put it (no invented post)", () => {
  const state = reduce(layout, [
    ...start(),
    ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
  ]);
  expect(state.agents.A_s1?.post).toBeNull();
  expect(standingAt(state, state.agents.A_s1 as never)).toBe("B1");
});

test("FR-WLD-04 TILO-T-WORLD: a room keeps its agents in the hall, and they settle to their posts after it adjourns", () => {
  const withHall = structuredClone(layout) as Layout;
  for (const b of withHall.semantic.levels[0]?.districts[0]?.buildings ?? [])
    if (b.id === "B3") (b as { common_type?: string }).common_type = "meeting_hall";
  const worked = [...start(), ...unit("A_s1", "B2"), ...chatter(TALK_WINDOW + 1)];
  let state = reduce(withHall, worked);
  expect(state.hall).toBe("B3");
  const room = { room_id: "R1", lead: "A_l1", agents: ["A_s1"] };
  state = applyEvent(state, ev("meeting.convened", "u_owner", "A_l1", room), withHall);
  expect(standingAt(state, state.agents.A_s1 as never)).toBe(state.hall);
  state = applyEvent(
    state,
    ev("meeting.adjourned", "u_owner", "A_l1", { room_id: "R1" }),
    withHall,
  );
  expect(standingAt(state, state.agents.A_s1 as never)).toBe("B2");
});
