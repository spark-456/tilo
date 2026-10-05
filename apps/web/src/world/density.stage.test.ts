// @vitest-environment happy-dom
// FR-WLD-14: the density mode changes rendering only. A switch between Friendly and Professional
// redraws the stage in place: characters get smaller and every tag carries its recorded state,
// and nothing is emitted or replayed (HR-1..HR-3, FR-WLD-09: no event, no new animation).
import type { Event, Layout } from "@tilo/contracts";
import { Container, Graphics } from "pixi.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { setDensity } from "../display/density";
import { AGENT_SCALE } from "./art/agent";
import { BUILDING_STATE, ISLAND_STATE } from "./runSummary";
import { runClientWorld } from "./runWorld";

const invert = (m: Record<string, string>) =>
  Object.fromEntries(Object.values(m).map((v) => [v, 1]));

// Pixi's Text needs a canvas the test runtime does not have, so a tag is a bare container whose
// label is its text: what matters here is which words the renderer asks for.
vi.mock("./art/labels", async () => {
  const { Container: C, Graphics: G } = await import("pixi.js");
  // 130 px wide, about a name and its state word at 12 px: tag placement needs a width to work with.
  const pill = (text: string) => {
    const c = Object.assign(new C(), { label: text });
    c.addChild(new G().rect(-65, -10, 130, 20).fill(0));
    return c;
  };
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

function stage(width = 900) {
  const world = new Container();
  const calls = { delivered: 0, seq: 0, render: 0 };
  const stop = runClientWorld({
    world,
    layout,
    size: () => ({ width, height: 600 }),
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
  const layers = () => {
    const [, objects, , labels] = content.children as Container[];
    return { objects, labels };
  };
  return { stop, calls, scales, tags, layers };
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

  it("a phone-sized stage keeps the names and drops the state words, which are unreadable there", () => {
    setDensity("professional");
    const phone = stage(390);
    const tags = phone.tags();
    expect(tags.length).toBeGreaterThan(0);
    expect(
      tags.some((t) =>
        /^(Town Hall|[A-Z][\w ]+) · (At work|Finished|Planned|Being built)$/.test(t),
      ),
    ).toBe(false);
    // Gate states and rank words are the same 6 px type: they go too, and the Policy tag keeps its word.
    expect(tags.some((t) => t.startsWith("Gate · "))).toBe(false);
    expect(tags.some((t) => /^(Director|Lead|Verifier|Specialist)$/.test(t))).toBe(false);
    phone.stop();
    const wide = stage();
    expect(wide.tags().some((t) => t.startsWith("Gate · "))).toBe(true); // a full-size stage keeps them
    wide.stop();
  });

  it("a building's tag keeps clear of the figures resting in front of any building (FR-WLD-14, 1920 stage)", () => {
    setDensity("professional");
    const s = stage(1400);
    const { objects, labels } = s.layers();
    const names = new Set(
      layout.semantic.levels.flatMap((l) =>
        l.districts.flatMap((d) => d.buildings.map((b) => b.name)),
      ),
    );
    const figures = (objects?.children ?? []).filter((c) => c.scale.x !== 1);
    const tags = (labels?.children ?? []).filter(
      (c) => c.visible && names.has(c.label.split(" · ")[0] ?? ""),
    );
    expect(figures.length).toBeGreaterThan(0);
    expect(tags.length).toBeGreaterThan(0);
    for (const t of tags) {
      for (const f of figures) {
        const across = Math.abs(t.x - f.x) < 65 + 18;
        const down = f.y - 30 * AGENT_SCALE < t.y + 10 && f.y + 6 > t.y - 10;
        expect(across && down, `${t.label} touches a figure at ${f.x},${f.y}`).toBe(false);
      }
    }
    s.stop();
  });

  it("a tag's state words are the Inspect panel's: one shared map", () => {
    setDensity("professional");
    const s = stage();
    const words = new Set(Object.values(BUILDING_STATE));
    const states = s
      .tags()
      .filter((t) => t.includes(" · ") && !t.startsWith("Gate · "))
      .map((t) => t.split(" · ")[1] ?? "");
    expect(states.length).toBeGreaterThan(0);
    for (const w of states) expect(words.has(w as never) || w in invert(ISLAND_STATE)).toBe(true);
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
