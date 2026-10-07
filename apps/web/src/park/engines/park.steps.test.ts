// NFR-01 (ticket NFR-01-LANDING): the city can be drawn in steps (`scene.steps`) so the shell never holds the main
// thread for the whole build on a phone. Pinned: the stepped scene is the same scene as the one-go `scene()` (same
// pictures, same movers, same free spots, day and night), it takes many steps (each a small slice), and the night
// colour map is not left switched on between two steps (an agent drawn by the page in between keeps its colours).
import { describe, expect, it } from "vitest";
import { canon, fakeEnv, serialiseH } from "../../../test-support/park/engineProto";
import { createPark } from "./park";
import type { AgentSpec, SceneOpts } from "./types";
import { createWorld } from "./world";

const engine = () => createPark(serialiseH as never, createWorld, fakeEnv as never);
const OPTS: SceneOpts = { w: 1600, h: 1000, vw: 1240, k: 1.9, still: false } as SceneOpts;

function drain<T>(steps: Generator<void, T, void>): { value: T; count: number } {
  let count = 0;
  for (;;) {
    const next = steps.next();
    if (next.done) return { value: next.value, count };
    count += 1;
  }
}

describe("NFR_01_LANDING_engine: the city in steps", () => {
  for (const night of [false, true]) {
    it(`NFR_01_LANDING_engine_stepped_scene_equals_the_one_go_scene_${night ? "night" : "day"}`, () => {
      const whole = engine().scene({ ...OPTS, night });
      const stepped = drain(engine().scene.steps({ ...OPTS, night }));
      expect(stepped.value.spots).toEqual(whole.spots);
      expect(JSON.stringify(canon(stepped.value.el))).toBe(JSON.stringify(canon(whole.el)));
      // many small slices, not one or two big ones
      expect(stepped.count).toBeGreaterThanOrEqual(20);
    });
  }

  it("NFR_01_LANDING_engine_the_night_colour_map_is_off_between_two_steps", () => {
    const park = engine();
    const walker: AgentSpec = { role: "builder", expr: "neutral", facing: "R" } as AgentSpec;
    const before = JSON.stringify(canon(park.agent(walker, 40, true)));
    const steps = park.scene.steps({ ...OPTS, night: true });
    for (let i = 0; i < 6; i++) {
      steps.next();
      expect(JSON.stringify(canon(park.agent(walker, 40, true)))).toBe(before);
    }
    steps.return(undefined as never);
  });
});
