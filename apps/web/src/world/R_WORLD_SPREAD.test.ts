import { readFileSync } from "node:fs";
import type { Event, Layout } from "@tilo/contracts";
import { describe, expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { reduce, standingAt } from "./reducer";

let seq = 0;
function event(type: string, actor: string, target: string, data: object = {}): Event {
  seq += 1;
  return {
    v: "1.0",
    id: `01JB5VQ${String(seq).padStart(19, "0")}`,
    seq,
    ts: "2026-10-18T08:00:00.000Z",
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
    summary: `${actor} ${type} ${target}`,
    cause: null,
    vis: "all",
    authz: null,
    data,
    trace: {},
  } as unknown as Event;
}

function movementLayout(): Layout {
  const layout = structuredClone(villageBasicLayout()) as unknown as Layout;
  for (const building of layout.semantic.levels[0]?.districts[0]?.buildings ?? []) {
    if (building.id === "B3") (building as { common_type?: string }).common_type = "your_desk";
    if (building.id === "B4") (building as { common_type?: string }).common_type = "expert_office";
  }
  return layout;
}

function placedAgents() {
  return [
    event("agent.spawned", "system", "A_l1", { role: "lead" }),
    event("agent.moved", "A_l1", "B1", { from: "B1" }),
    event("agent.spawned", "A_l1", "A_s1", { role: "specialist" }),
    event("agent.moved", "A_s1", "B2", { from: "B1" }),
  ];
}

describe("R-WORLD-SPREAD recorded conversation movement", () => {
  test("R-WORLD-SPREAD a handoff carries its actor to the receiving agent", () => {
    seq = 0;
    const layout = movementLayout();
    const state = reduce(layout, [
      ...placedAgents(),
      event("agent.handoff", "A_s1", "A_l1", { envelope: { summary: "Done" } }),
    ]);
    expect(state.agents.A_s1?.location).toBe("B1");
    expect(standingAt(state, state.agents.A_s1 as never)).toBe("B1");
  });

  test.each([
    ["the owner", "u_owner", null, "B3"],
    ["a Team Lead", "tl_research", "research", "B4"],
  ])(
    "R-WORLD-SPREAD a question routed to %s walks to its named office",
    (_, target, domain, at) => {
      seq = 0;
      const layout = movementLayout();
      const state = reduce(layout, [
        ...placedAgents(),
        event("question.routed", "A_s1", target, { card_id: "card_1", domain }),
      ]);
      expect(state.agents.A_s1?.location).toBe(at);
    },
  );

  test("R-WORLD-SPREAD a routed question invents no destination when the layout names no matching office", () => {
    seq = 0;
    const layout = villageBasicLayout() as unknown as Layout;
    const state = reduce(layout, [
      ...placedAgents(),
      event("question.routed", "A_s1", "u_owner", { card_id: "card_1", domain: null }),
    ]);
    expect(state.agents.A_s1?.location).toBe("B2");
  });
});

test("R-WORLD-SPREAD visible building art leaves a wider gutter without moving its recorded centre", () => {
  seq = 0;
  const layout = movementLayout();
  const state = reduce(layout, [
    event("building.planned", "A_dir", "B1"),
    event("building.planned", "A_dir", "B2"),
  ]);
  const frame = frameOf(layout, state);
  for (const building of frame.buildings) {
    const source = layout.geometry?.buildings.find((item) => item.id === building.id)?.footprint;
    expect(source).toBeDefined();
    if (!source) throw new Error(`missing source footprint for ${building.id}`);
    expect(building.rect.w).toBeLessThan(source.w);
    expect(building.rect.d).toBeLessThan(source.d);
    expect(building.rect.x + building.rect.w / 2).toBe(source.x + source.w / 2);
    expect(building.rect.y + building.rect.d / 2).toBe(source.y + source.d / 2);
  }
});

test("R-WORLD-SPREAD the main stage is larger and its road strips stay readable", () => {
  const view = readFileSync(new URL("../worldView/WorldView.css", import.meta.url), "utf8");
  const ground = readFileSync(new URL("./art/ground.ts", import.meta.url), "utf8");
  expect(view).toContain("grid-template-columns: minmax(0, 1fr) 300px");
  expect(view).toContain("height: clamp(480px, 72vh, 840px)");
  expect(ground).toContain("strip(g, path, 0.78, PALETTE.road, lift)");
});
