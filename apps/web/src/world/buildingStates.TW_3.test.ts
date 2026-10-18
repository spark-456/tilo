// @vitest-environment happy-dom
import type { Event, Layout } from "@tilo/contracts";
import { describe, expect, it, vi } from "vitest";
import tokens from "../design/tokens";
import { completedTag, failedTag, needsTag } from "./art/labels";
import { applyEvent, createInitialState } from "./reducer";
import { BUILDING_STATE } from "./runSummary";

function makeLayout(hasHall = true, hasDock = true): Layout {
  return {
    manifest: {
      world_id: "w_test",
      schema_version: "1.0",
      created_at: "2026-10-18T00:00:00Z",
      layout_engine_version: "1.0",
      hash: "abc",
    },
    semantic: {
      levels: [
        {
          id: "lvl-1",
          name: "Level 1",
          tier: 1,
          summary: "First level",
          districts: [
            {
              id: "dst-1",
              name: "District 1",
              summary: "First district",
              palette: "civic",
              buildings: [
                ...(hasHall
                  ? [
                      {
                        id: "b-hall",
                        name: "Meeting Hall",
                        summary: "Hall for convenings",
                        palette: "civic",
                        common_type: "meeting_hall" as const,
                      },
                    ]
                  : []),
                ...(hasDock
                  ? [
                      {
                        id: "b-dock",
                        name: "Delivery Dock",
                        summary: "Dock for shipments",
                        palette: "civic",
                        common_type: "delivery_dock" as const,
                      },
                    ]
                  : []),
                {
                  id: "b-step",
                  name: "Compute Node",
                  summary: "Worker step",
                  palette: "work",
                },
              ],
            },
          ],
        },
      ],
      agents: [],
      gates: [],
      islands: [],
    },
    geometry: {
      bounds: { min_x: 0, min_y: 0, max_x: 1000, max_y: 1000 },
      iso_transform: { origin_x: 0, origin_y: 0, scale_x: 1, scale_y: 0.5 },
      levels: [],
      districts: [],
      buildings: [],
      connectors: [],
      islands: [],
      gates: [],
    },
  } as unknown as Layout;
}

function baseEvent(seq: number, type: string, target: string, actor = "system"): Event {
  return {
    v: "1.0",
    id: `ev-${seq}`,
    seq,
    ts: "2026-10-18T10:00:00.000Z",
    world_id: "w_test",
    run_id: "r_test_1",
    type,
    actor,
    target,
    level: "lvl-1",
    district: "dst-1",
    item: null,
    severity: "fyi",
    credits: 0,
    summary: `${type} on ${target}`,
    cause: null,
    vis: "all",
    authz: null,
    data: {},
    trace: {
      model_role: null,
      profile: null,
      tokens_in: null,
      tokens_out: null,
      tool: null,
      latency_ms: null,
      archive_ref: null,
    },
  } as unknown as Event;
}

describe("TW-3 Building states and Hall/Dock lifecycle", () => {
  it("detects Meeting Hall and Delivery Dock from semantic layout", () => {
    const layout = makeLayout(true, true);
    const state = createInitialState(layout);
    expect(state.hall).toBe("b-hall");
    expect(state.dock).toBe("b-dock");
    expect(state.buildings["b-hall"]?.status).toBe("hidden");
    expect(state.buildings["b-dock"]?.status).toBe("hidden");
  });

  it("handles missing Hall or Dock gracefully", () => {
    const layout = makeLayout(false, false);
    const state = createInitialState(layout);
    expect(state.hall).toBeNull();
    expect(state.dock).toBeNull();
  });

  it("activates Meeting Hall and Delivery Dock to operational on world.planned", () => {
    const layout = makeLayout(true, true);
    const initial = createInitialState(layout);

    const plannedEv = baseEvent(1, "world.planned", "w_test");
    const next = applyEvent(initial, plannedEv, layout);

    expect(next.buildings["b-hall"]?.status).toBe("operational");
    expect(next.buildings["b-dock"]?.status).toBe("operational");
    // Normal building remains hidden until its own lifecycle event
    expect(next.buildings["b-step"]?.status).toBe("hidden");
  });

  it("transitions building through planned -> constructing -> completed", () => {
    const layout = makeLayout(true, true);
    let state = createInitialState(layout);

    state = applyEvent(state, baseEvent(1, "building.planned", "b-step"), layout);
    expect(state.buildings["b-step"]?.status).toBe("planned");

    state = applyEvent(state, baseEvent(2, "building.constructing", "b-step"), layout);
    expect(state.buildings["b-step"]?.status).toBe("constructing");

    state = applyEvent(state, baseEvent(3, "building.completed", "b-step"), layout);
    expect(state.buildings["b-step"]?.status).toBe("completed");
  });

  it("transitions building to needs on approval.requested and restores to operational on approval.resolved", () => {
    const layout = makeLayout(true, true);
    let state = createInitialState(layout);
    state = applyEvent(state, baseEvent(1, "world.planned", "w_test"), layout);

    state = applyEvent(state, baseEvent(2, "approval.requested", "b-step"), layout);
    expect(state.buildings["b-step"]?.status).toBe("needs");

    state = applyEvent(state, baseEvent(3, "approval.resolved", "b-step"), layout);
    expect(state.buildings["b-step"]?.status).toBe("operational");
  });

  it("transitions building to failed on world.failed or agent.blocked", () => {
    const layout = makeLayout(true, true);
    let state = createInitialState(layout);

    // Targeted world.failed
    state = applyEvent(state, baseEvent(1, "world.failed", "b-step"), layout);
    expect(state.buildings["b-step"]?.status).toBe("failed");

    // agent.blocked targeting building
    state = applyEvent(
      state,
      baseEvent(2, "agent.blocked", "b-step", "system"),
      layout,
    );
    expect(state.buildings["b-step"]?.status).toBe("failed");
  });

  it("completes Delivery Dock on artifact.delivered", () => {
    const layout = makeLayout(true, true);
    let state = createInitialState(layout);
    state = applyEvent(state, baseEvent(1, "world.planned", "w_test"), layout);
    expect(state.buildings["b-dock"]?.status).toBe("operational");

    state = applyEvent(state, baseEvent(2, "artifact.delivered", "art-1"), layout);
    expect(state.buildings["b-dock"]?.status).toBe("completed");
  });

  it("provides correct labels in BUILDING_STATE dictionary", () => {
    expect(BUILDING_STATE.needs).toBe("Needs you");
    expect(BUILDING_STATE.failed).toBe("Failed");
    expect(BUILDING_STATE.planned).toBe("Planned");
    expect(BUILDING_STATE.constructing).toBe("Being built");
    expect(BUILDING_STATE.completed).toBe("Finished");
  });

  it("creates needsTag, failedTag, and completedTag pills with signal colors", () => {
    class MockCanvasRenderingContext2D {
      font = "";
      measureText(text: string) {
        return { width: text.length * 8 };
      }
    }
    (globalThis as unknown as { CanvasRenderingContext2D: unknown }).CanvasRenderingContext2D =
      MockCanvasRenderingContext2D;

    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(((kind: string) => {
      if (kind === "2d") {
        return new MockCanvasRenderingContext2D() as unknown as CanvasRenderingContext2D;
      }
      return null;
    }) as never);

    const nTag = needsTag("Approval Wait");
    expect(nTag).toBeDefined();

    const fTag = failedTag("Build Broken");
    expect(fTag).toBeDefined();

    const cTag = completedTag("Build Finished");
    expect(cTag).toBeDefined();

    expect(tokens.color.signal.needs).toBeDefined();
    expect(tokens.color.signal.blocked).toBeDefined();
    expect(tokens.color.signal.done).toBeDefined();
  });
});
