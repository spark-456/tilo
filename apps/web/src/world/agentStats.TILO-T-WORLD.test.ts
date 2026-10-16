/**
 * TILO-T-WORLD step 3 (FR-WLD-06, HR-1): the stats card of an agent is built from the recorded events only: name and
 * role, where it stands and its task, units done, tools used, credits spent and the last three things it said.
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { agentStatsOf } from "./agentStats";

const layout = villageBasicLayout() as unknown as Layout;

let n = 0;
function ev(
  type: string,
  actor: string,
  target: string,
  data: object = {},
  more: Partial<Event> = {},
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
    summary: `${type} summary`,
    cause: null,
    vis: "all",
    authz: null,
    data,
    trace: {},
    ...more,
  } as unknown as Event;
}

const run = (): Event[] => {
  n = 0;
  return [
    ev("agent.spawned", "A_dir", "A_l1", { role: "lead" }),
    ev("agent.moved", "A_l1", "B1", { from: "B1" }),
    ev("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
    ev(
      "agent.assigned",
      "A_l1",
      "A_s1",
      { unit: "U1" },
      { summary: "The Lead gave it: Triage the inbox" },
    ),
    ev("agent.moved", "A_s1", "B2", { from: "B1" }),
    ev("agent.working", "A_s1", "B2", { unit: "U1" }, { trace: { tool: "gmail.search" } } as never),
    ev("agent.working", "A_s1", "B2", { unit: "U1" }, {
      credits: 1.5,
      trace: { tool: "sheets.read" },
    } as never),
    ev("agent.working", "A_s1", "B2", { unit: "U1" }, {
      credits: 0.5,
      trace: { tool: "gmail.search" },
    } as never),
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "Triaged 12 emails." } }),
  ];
};

test("FR-WLD-06 TILO-T-WORLD stats: name, role, task, place, units done, tools and credits all come from events", () => {
  const stats = agentStatsOf(layout, run()).get("A_s1");
  expect(stats?.name).toBe("Specialist 1");
  expect(stats?.role).toBe("Specialist");
  expect(stats?.task).toBe("Triage the inbox");
  expect(stats?.at?.name).toBe("Reply Desk");
  expect(stats?.unitsDone).toBe(1);
  expect(stats?.tools).toEqual(["gmail.search", "sheets.read"]);
  expect(stats?.credits).toBe(2);
  expect(stats?.workCalls).toBe(3);
});

test("FR-WLD-06 TILO-T-WORLD stats: the last three things an agent said, newest last, with the real words", () => {
  n = 0;
  const events = [
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "one" } }),
    ev("agent.help_requested", "A_s1", "A_l1", {}, { summary: "two" }),
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "three" } }),
    ev("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "four" } }),
  ];
  const said = agentStatsOf(layout, events).get("A_s1")?.said;
  expect(said?.map((m) => m.text)).toEqual(["two", "three", "four"]);
});

test("FR-WLD-06 TILO-T-WORLD stats: an agent with no events shows zeros and no place, never a guess", () => {
  const stats = agentStatsOf(layout, []).get("A_s2");
  expect(stats).toMatchObject({
    unitsDone: 0,
    credits: 0,
    workCalls: 0,
    task: null,
    at: null,
    status: "waiting",
  });
  expect(stats?.tools).toEqual([]);
  expect(stats?.said).toEqual([]);
});

test("FR-WLD-06 TILO-T-WORLD stats: status follows the record: working, finished, and in a meeting", () => {
  const events = run();
  expect(agentStatsOf(layout, events.slice(0, 7)).get("A_s1")?.status).toBe("working");
  expect(agentStatsOf(layout, events).get("A_s1")?.status).toBe("handing over");
  n = events.length;
  const idle = [
    ...events,
    ev("artifact.created", "A_l1", "a"),
    ev("artifact.created", "A_l1", "a"),
    ev("artifact.created", "A_l1", "a"),
  ];
  expect(agentStatsOf(layout, idle).get("A_s1")?.status).toBe("finished");
});
