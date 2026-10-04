// @vitest-environment happy-dom
// FR-WLD-14: the density mode changes rendering only. A switch between Friendly and Professional
// redraws the stage in place: characters get smaller and every tag carries its recorded state,
// and nothing is emitted or replayed (HR-1..HR-3, FR-WLD-09: no event, no new animation).
import type { Event, Layout } from "@tilo/contracts";
import { Container } from "pixi.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { setDensity } from "../display/density";
import { AGENT_SCALE } from "./art/agent";
import { runClientWorld } from "./runWorld";

// Pixi's Text needs a canvas the test runtime does not have, so a tag is a bare container whose
// label is its text: what matters here is which words the renderer asks for.
vi.mock("./art/labels", async () => {
  const { Container: C } = await import("pixi.js");
  const pill = (text: string) => Object.assign(new C(), { label: text });
  return {
    makePill: (text: string) => pill(text),
    buildingTag: pill,
    districtTag: (text: string) => pill(text),
    islandTag: pill,
    policyTag: () => pill("Policy"),
  };
});

const layout = villageBasicLayout() as unknown as Layout;
const events = villageBasicEvents() as unknown as Event[];

function stage() {
  const world = new Container();
  const calls = { delivered: 0, seq: 0, render: 0 };
  const stop = runClientWorld({
    world,
    layout,
    size: () => ({ width: 900, height: 600 }),
    requestRender: () => {
      calls.render += 1;
    },
    reducedMotion: () => false,
    onSeq: () => {
      calls.seq += 1;
    },
    watch: (on) => {
      for (const e of events) {
        calls.delivered += 1;
        on(e);
      }
      return () => undefined;
    },
  });
  const content = world.children[world.children.length - 1] as Container;
  const [, objects, , labels] = content.children as Container[];
  const scales = () => [
    ...new Set((objects?.children ?? []).map((c) => c.scale.x).filter((s) => s !== 1)),
  ];
  const tags = () =>
    (labels?.children ?? [])
      .filter((c) => c.visible)
      .map((c) => c.label)
      .sort();
  return { stop, calls, scales, tags };
}

beforeEach(() => setDensity("friendly"));
afterEach(() => setDensity("friendly"));

describe("FR-WLD-14 the stage follows the density mode, read at draw time", () => {
  it("Professional draws smaller characters and puts the recorded state in every tag", () => {
    const s = stage();
    expect(s.scales()).toEqual([AGENT_SCALE]);
    const friendlyTags = s.tags();
    expect(friendlyTags.length).toBeGreaterThan(0);
    expect(friendlyTags.some((t) => t.includes(" · "))).toBe(false);

    setDensity("professional");
    const [small] = s.scales();
    expect(s.scales()).toHaveLength(1);
    expect(small).toBeLessThan(AGENT_SCALE);
    const proTags = s.tags();
    expect(proTags.length).toBeGreaterThan(friendlyTags.length); // rank tags and gate states
    expect(proTags.some((t) => /· (Working|Done|Planned|Being built)$/.test(t))).toBe(true);
    expect(proTags.some((t) => /^(Director|Lead|Verifier|Specialist)$/.test(t))).toBe(true); // by rank

    setDensity("friendly");
    expect(s.scales()).toEqual([AGENT_SCALE]);
    expect(s.tags()).toEqual(friendlyTags);
    s.stop();
  });

  it("a switch redraws in place: no event is delivered or replayed, no seq change, no new frame loop", () => {
    const raf = vi.spyOn(globalThis, "requestAnimationFrame");
    const s = stage();
    const before = { ...s.calls };
    const frames = raf.mock.calls.length;
    setDensity("professional");
    setDensity("friendly");
    setDensity("professional");
    expect(s.calls.delivered).toBe(before.delivered);
    expect(s.calls.seq).toBe(before.seq); // the run's position is not touched
    expect(s.calls.render).toBeGreaterThan(before.render); // it was redrawn
    expect(raf.mock.calls.length).toBe(frames); // and nothing started animating
    s.stop();
    raf.mockRestore();
  });

  it("a stopped stage ignores a switch", () => {
    const s = stage();
    s.stop();
    const render = s.calls.render;
    setDensity("professional");
    expect(s.calls.render).toBe(render);
  });
});
