// FR-WLD-04 / PRD 9.1, 9.4 (Bundle B of #227): what the stage is told to draw follows the layout
// and the recorded events only. A building's look is its recorded status, a gate's look is what
// the approval and policy events say, nothing else changes the picture (HR-1, HR-5, HR-7).
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { reduce } from "./reducer";

const layout = villageBasicLayout() as unknown as Layout;
const events = villageBasicEvents() as unknown as Event[];
const at = (seq: number) =>
  frameOf(
    layout,
    reduce(
      layout,
      events.filter((e) => e.seq <= seq),
    ),
  );
const status = (seq: number, id: string) => at(seq).buildings.find((b) => b.id === id)?.status;
const gate = (seq: number) => at(seq).gates.find((g) => g.id === "G1")?.state;

test("FR-WLD-04 frame: nothing is drawn for a building until building.planned names it", () => {
  expect(at(6).buildings).toEqual([]);
  expect(status(7, "B1")).toBe("planned");
  expect(status(7, "B2")).toBeUndefined();
});

test("FR-WLD-04 frame: a building's status follows planned, constructing, operational, completed", () => {
  expect([8, 21, 23, 40].map((seq) => status(seq, "B1"))).toEqual([
    "planned",
    "constructing",
    "operational",
    "completed",
  ]);
  expect(status(40, "B3")).toBe("planned"); // never built in this run: still a plan
});

test("FR-WLD-04 frame: events with no world effect leave the whole frame as it was (HR-5)", () => {
  // 35 and 36 are channel messages; 22 is a data transfer: none of them touches a drawn thing.
  expect(at(35)).toEqual(at(34));
  expect(at(36)).toEqual(at(35));
  expect(at(22)).toEqual(at(21));
});

test("FR-WLD-04 frame: districts, plates, roads, bridges, islands and gates come from the solver", () => {
  const f = at(0);
  const g = layout.geometry;
  expect(f.plates.map((p) => p.rect)).toEqual(g?.levels.map((l) => l.plate));
  expect(f.districts.map((d) => d.rect)).toEqual(g?.districts.map((d) => d.plot));
  expect(f.roads.map((r) => r.points)).toEqual(g?.roads.map((r) => r.path));
  expect(f.bridges.map((b) => b.points)).toEqual(g?.bridges.map((b) => b.path));
  expect(f.islands.map((i) => [i.id, i.rect])).toEqual(g?.islands.map((i) => [i.id, i.plot]));
  expect(f.gates.map((x) => x.cell)).toEqual(g?.gates.map((x) => x.cell));
  expect(f.districts[0]?.name).toBe("Mail"); // names are the layout's, not invented
});

test("HR-7 frame: a gate is shut until an event opens it, and a policy opening is its own look", () => {
  expect(gate(0)).toBe("closed");
  expect(gate(34)).toBe("waiting"); // approval.requested
  expect(gate(37)).toBe("open"); // approval.resolved by a person, option approve
  const byPolicy = events.map((e) =>
    e.seq === 37
      ? ({
          ...e,
          type: "policy.applied",
          authz: { by: "policy", ref: "pol_autopilot_l2", at: e.ts },
        } as unknown as Event)
      : e,
  );
  const state = reduce(layout, byPolicy);
  expect(frameOf(layout, state).gates[0]?.state).toBe("policy");
});

test("HR-7 frame: an approval that is held, or one nobody with authority made, does not open the gate", () => {
  const edit = (patch: Record<string, unknown>) =>
    events.map((e) => (e.seq === 37 ? ({ ...e, ...patch } as unknown as Event) : e));
  const held = edit({ data: { ...(events[36]?.data as object), option: "hold" } });
  expect(frameOf(layout, reduce(layout, held)).gates[0]?.state).toBe("closed");
  const noAuthz = edit({ authz: null });
  expect(frameOf(layout, reduce(layout, noAuthz)).gates[0]?.state).toBe("waiting");
});

test("FR-WLD-04 frame: an agent stands in front of its building, fanned out by roster place", () => {
  const f = at(24);
  const b1 = f.buildings.find((b) => b.id === "B1");
  const s1 = f.agents.find((a) => a.id === "A_s1");
  expect(s1).toBeDefined();
  if (!b1 || !s1) return;
  expect(s1.cy).toBeGreaterThan(b1.cy); // nearer the viewer than the building's centre
  const lead = f.agents.find((a) => a.id === "A_l1");
  const same = lead && lead.cx === s1.cx && lead.cy === s1.cy;
  expect(same).toBe(false); // two agents never stack on one spot
});

test("FR-WLD-04 frame: agent rank is carried for the figure's shape, and bounds frame the world", () => {
  const f = at(24);
  expect(f.agents.map((a) => a.rank).sort()).toEqual(
    f.agents.map((a) => layout.semantic.agents.find((x) => x.id === a.id)?.rank).sort(),
  );
  const { x0, y0, x1, y1 } = f.bounds;
  expect(x1).toBeGreaterThan(x0);
  expect(y1).toBeGreaterThan(y0);
  expect(at(0).bounds).toEqual(at(44).bounds); // the same for every state: the stage frames once
});

test("FR-WLD-04 frame: stacked levels rise by index and a missing geometry draws nothing", () => {
  const two = structuredClone(layout) as Layout;
  if (!two.geometry) throw new Error("fixture has geometry");
  two.geometry.levels.push({ id: "L2", index: 1, plate: { x: 0, y: 0, w: 20, d: 14 } });
  const lifts = frameOf(two, reduce(two, [])).plates.map((p) => p.lift);
  expect(lifts[0]).toBe(0);
  expect(lifts[1]).toBeGreaterThan(0);
  const unsolved = { ...layout, geometry: null } as Layout;
  const f = frameOf(unsolved, reduce(unsolved, events));
  expect([f.plates, f.districts, f.buildings, f.agents].map((l) => l.length)).toEqual([0, 0, 0, 0]);
});
