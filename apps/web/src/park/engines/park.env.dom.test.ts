// @vitest-environment happy-dom
// WEB-1b: in a DOM environment (the repo's tests use happy-dom) createPark works with no injected env:
// the defaults are the platform's own Blob and URL.createObjectURL. Injecting an env bypasses them. The
// port sets no window global (the prototype's `window.TiloWorld` / `window.TiloPark` are not carried over).
import { afterEach, describe, expect, it, vi } from "vitest";
import { plan, richPlan } from "../../../test-support/park/engineCases";
import {
  type Engine,
  type Json,
  type TestH,
  call,
  canon,
  fakeEnv,
  serialiseH,
} from "../../../test-support/park/engineProto";
import { createPark } from "./park";
import { createWorld } from "./world";

type MakePark = (h: TestH, makeWorld: typeof createWorld, env?: unknown) => Engine;
const make = (env?: unknown): Engine =>
  (createPark as unknown as MakePark)(serialiseH, createWorld, env);
const srcOf = (node: unknown): string =>
  String((canon(node) as { props?: Record<string, Json> }).props?.src);

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WEB_1b_park_env_dom: default env in happy-dom", () => {
  it("WEB_1b_park_env_dom_this_test_really_runs_with_a_window", () => {
    expect(typeof window).toBe("object");
    expect(typeof document).toBe("object");
  });

  it("WEB_1b_park_env_dom_defaults_work_without_injection_and_use_URL_createObjectURL", () => {
    const spy = vi.spyOn(URL, "createObjectURL");
    const park = make();
    const src = srcOf(call(park, "building", "library", "active", "research", 100, false));
    expect(src).toMatch(/^blob:/);
    expect(spy).toHaveBeenCalledTimes(1);
    const blob = spy.mock.calls[0]?.[0] as Blob;
    expect(blob.type).toBe("image/svg+xml");
    expect(blob.size).toBeGreaterThan(100);
  });

  it(
    "WEB_1b_park_env_dom_a_whole_scene_and_a_world_work_with_defaults",
    { timeout: 60_000 },
    () => {
      const park = make();
      const scene = call(park, "scene", { w: 600, h: 400 }) as { el: unknown; spots: unknown[] };
      expect(JSON.stringify(canon(scene.el))).toContain("blob:");
      expect(srcOf(call(park, "world", richPlan(), { night: true }))).toMatch(/^blob:/);
      expect(srcOf(call(park, "agent", { role: "builder", expr: "focused" }, 90, false))).toMatch(
        /^blob:/,
      );
    },
  );

  it("WEB_1b_park_env_dom_an_injected_env_bypasses_the_platform", () => {
    const spy = vi.spyOn(URL, "createObjectURL");
    const park = make(fakeEnv);
    const src = srcOf(call(park, "world", plan("fresh"), {}));
    expect(src.startsWith("blob:image/svg+xml|<svg")).toBe(true);
    expect(spy).not.toHaveBeenCalled();
  });

  it("WEB_1b_park_env_dom_sets_no_window_global", () => {
    const before = new Set(Object.getOwnPropertyNames(window));
    const park = make();
    call(park, "world", plan("fresh"), {});
    call(park, "scene", { w: 300, h: 200 });
    const added = Object.getOwnPropertyNames(window).filter((k) => !before.has(k));
    expect(added).toEqual([]);
    expect("TiloWorld" in window).toBe(false);
    expect("TiloPark" in window).toBe(false);
  });

  it("WEB_1b_park_env_dom_the_world_engine_alone_needs_nothing_from_the_dom", () => {
    const w = createWorld(serialiseH) as unknown as Engine;
    expect(Object.keys(call(w, "soloAgent", { role: "builder" }) as object).sort()).toEqual([
      "children",
      "props",
      "tag",
    ]);
    expect("TiloWorld" in window).toBe(false);
  });
});
