// WEB-1b (docs/web-app-rebuild-plan.md sections 2, 5, 9 BQ-WEB-5; ADR-0003a 3): the TypeScript port of
// tilo-park.js is the prototype, tree for tree. The prototype runs in a Node vm (stub `window`, fake
// Blob and URL.createObjectURL that return the SVG text itself, so the image sources compare as strings);
// createPark(h, createWorld, env) runs with the same serialising `h`, the same inputs and the same fakes
// handed in through `env`. The trees must be identical.
//
// Pinned decisions (each is listed in the WEB-1b report):
//  - createPark's second argument is the createWorld FACTORY, not an instance. The prototype builds its own
//    world engine on a private string-building, colour-mapping `h` (night and mute remap colours as the
//    SVG text is written), so an already-built world engine cannot be reused.
//  - WEB-1b added no animation (BQ-WEB-3, ADR-0003a 5): the port equalled the prototype with still: true for
//    every input. WEB-MOTION-1 makes `still` and `k` real (the live movers are pinned in park.motion.test.ts);
//    this file compares the frozen drawing (`still: true` on both sides).
import * as fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BUILDING_STATES,
  EXPRESSIONS,
  SCENE_OPTION_SETS,
  plan,
  realPlans,
  richPlan,
} from "../../../test-support/park/engineCases";
import {
  type Engine,
  type Json,
  type TestH,
  call,
  canon,
  fakeEnv,
  motionLeaks,
  protoPark,
  protoWorld,
  sameAsPrototype,
  serialiseH,
  size,
} from "../../../test-support/park/engineProto";
import { createPark } from "./park";
import { createWorld } from "./world";

const SLOW = { timeout: 180_000 };

type MakePark = (h: TestH, makeWorld: typeof createWorld, env?: unknown) => Engine;
/** The port, with the fakes injected through `env`. */
function portPark(env: unknown = fakeEnv, h: TestH = serialiseH): Engine {
  return (createPark as unknown as MakePark)(h, createWorld, env);
}

function pair() {
  return { port: portPark(), proto: protoPark() };
}
type Pair = ReturnType<typeof pair>;

/** Same call on both engines. The port is compared with the prototype's frozen (`still`) drawing. */
function both(p: Pair, name: string, ...args: unknown[]): string | null {
  return sameAsPrototype(call(p.port, name, ...args), call(p.proto, name, ...args), {
    frozenWalkers: true,
  });
}
function bothScene(p: Pair, opts: Record<string, unknown> | undefined): string | null {
  // WEB-MOTION-1: the port now animates by default, as the prototype does, so the frozen drawings are compared:
  // both engines are asked for the same options with `still: true` (live motion: park.motion.test.ts).
  const port = call(p.port, "scene", { ...(opts ?? {}), still: true });
  const proto = call(p.proto, "scene", { ...(opts ?? {}), still: true });
  return sameAsPrototype(port, proto, { frozenWalkers: true });
}

const kitKeys = Object.keys(protoWorld().KIT as object);
const roleKeys = Object.keys(protoWorld().ROLE as object);

afterEach(() => {
  vi.restoreAllMocks();
});

/** All nodes of a canonical tree that satisfy `pick`. */
function findAll(
  j: Json,
  pick: (n: { tag: string; props: Record<string, Json> | null; children: Json[] }) => boolean,
): number {
  let n = 0;
  const walk = (x: Json) => {
    if (Array.isArray(x)) return x.forEach(walk);
    if (x && typeof x === "object") {
      if ("tag" in x && "props" in x && "children" in x && pick(x as never)) n++;
      Object.values(x).forEach(walk);
    }
  };
  walk(j);
  return n;
}
const styleOf = (n: { props: Record<string, Json> | null }): Record<string, Json> =>
  ((n.props?.style as Record<string, Json> | undefined) ?? {}) as Record<string, Json>;

describe("WEB_1b_park_surface: createPark(h, createWorld, env) returns what TiloPark(h) returns", () => {
  it("WEB_1b_park_surface_returns_scene_world_building_agent", () => {
    expect(Object.keys(portPark()).sort()).toEqual(["agent", "building", "scene", "world"]);
    expect(Object.keys(protoPark()).sort()).toEqual(["agent", "building", "scene", "world"]);
    for (const m of ["scene", "world", "building", "agent"])
      expect(typeof portPark()[m], m).toBe("function");
  });

  it("WEB_1b_park_surface_scene_returns_el_and_spots", () => {
    const r = call(portPark(), "scene", { w: 400, h: 300 }) as { el: unknown; spots: unknown[] };
    expect(Object.keys(r).sort()).toEqual(["el", "spots"]);
    expect(Array.isArray(r.spots)).toBe(true);
    const el = canon(r.el) as { tag: string };
    expect(el.tag).toBe("div");
  });
});

describe("WEB_1b_park_scene: scene(o) for the design's sizes, day and night, and every knob", () => {
  it.each(SCENE_OPTION_SETS.map((s) => [s.name, s.opts] as const))(
    "WEB_1b_park_scene_%s",
    SLOW,
    (_n, opts) => {
      expect(bothScene(pair(), opts)).toBeNull();
    },
  );

  it("WEB_1b_park_scene_reference_is_large_and_has_images_and_spots", SLOW, () => {
    const r = call(protoPark(), "scene", { w: 1600, h: 1000, vw: 1240, still: true }) as {
      el: unknown;
      spots: Record<string, unknown>[];
    };
    expect(size(r.el)).toBeGreaterThan(500);
    expect(JSON.stringify(canon(r.el))).toContain("<svg");
    expect(r.spots.length).toBeGreaterThan(5);
    for (const s of r.spots) {
      expect(Object.keys(s).sort()).toEqual(["area", "st", "x", "y"]);
      expect(["active", "idle"]).toContain(s.st);
    }
  });

  it("WEB_1b_park_scene_spots_equal_the_prototype_spots_exactly", SLOW, () => {
    for (const opts of [
      { w: 1600, h: 1000, vw: 1240 },
      { w: 390, h: 844 },
      { w: 1440, h: 900, seed: 5 },
    ]) {
      const p = pair();
      const a = (call(p.port, "scene", opts) as { spots: unknown }).spots;
      const b = (call(p.proto, "scene", { ...opts, still: true }) as { spots: unknown }).spots;
      expect(sameAsPrototype(a, b), JSON.stringify(opts)).toBeNull();
    }
  });

  it("WEB_1b_park_scene_night_and_mute_and_seed_change_the_picture", SLOW, () => {
    const p = pair();
    const day = call(p.port, "scene", { w: 600, h: 400 });
    expect(
      sameAsPrototype(call(p.port, "scene", { w: 600, h: 400, night: true }), day),
    ).not.toBeNull();
    expect(
      sameAsPrototype(call(p.port, "scene", { w: 600, h: 400, mute: 0.7 }), day),
    ).not.toBeNull();
    expect(
      sameAsPrototype(call(p.port, "scene", { w: 600, h: 400, seed: 24 }), day),
    ).not.toBeNull();
  });
});

describe("WEB_1b_park_motion: movers are drawn frozen when still and run otherwise (BQ-WEB-3, WEB-MOTION-1)", () => {
  it(
    "WEB_1b_park_motion_cars_and_walkers_layers_exist_in_both_modes_frozen_only_when_still",
    SLOW,
    () => {
      for (const still of [false, true, undefined]) {
        const r = call(portPark(), "scene", {
          w: 1000,
          h: 700,
          ...(still === undefined ? {} : { still }),
        }) as { el: unknown };
        const tree = canon(r.el);
        const movers = findAll(tree, (n) => styleOf(n).willChange === "transform");
        expect(movers, `movers with still=${still}`).toBeGreaterThan(3);
        const frozen = findAll(
          tree,
          (n) =>
            styleOf(n).willChange === "transform" &&
            String(styleOf(n).transform ?? "").startsWith("translate("),
        );
        // Still: every mover sits at a fixed translate(). Live (the prototype's default): none does, each
        // runs mvXY (park.motion.test.ts pins the durations, phases and travel).
        expect(frozen, `movers at a fixed translate() with still=${still}`).toBe(
          still === true ? movers : 0,
        );
        const walkers = findAll(tree, (n) =>
          String(styleOf(n).backgroundImage ?? "").startsWith('url("blob:'),
        );
        expect(walkers, "walkers are sprite sheets").toBeGreaterThan(0);
      }
    },
  );

  it(
    "WEB_1b_park_motion_k_changes_nothing_when_still_and_still_false_is_not_the_frozen_drawing",
    SLOW,
    () => {
      const p = pair();
      const base = { w: 800, h: 560, seed: 4 };
      const ref = call(p.port, "scene", { ...base, still: true });
      for (const extra of [{ still: true }, { k: 2, still: true }]) {
        expect(
          sameAsPrototype(call(portPark(), "scene", { ...base, ...extra }), ref),
          JSON.stringify(extra),
        ).toBeNull();
      }
      for (const extra of [{}, { still: false }, { k: 2, still: false }]) {
        expect(
          sameAsPrototype(call(portPark(), "scene", { ...base, ...extra }), ref),
          JSON.stringify(extra),
        ).not.toBeNull();
      }
    },
  );

  it("WEB_1b_park_motion_the_reference_really_animates_when_still_is_off", () => {
    // Guards the equality above: the prototype with still: false carries mvXY, waddle and sprite2.
    const text = JSON.stringify(
      canon(call(protoPark(), "scene", { w: 800, h: 560, seed: 4, still: false })),
    );
    expect(text).toMatch(/mvXY/);
    expect(text).toMatch(/waddle/);
    expect(text).toMatch(/sprite2/);
  });

  it(
    "WEB_1b_park_motion_only_a_live_scene_carries_an_animation_name_a_keyframe_or_a_css_variable_for_it",
    SLOW,
    () => {
      const p = portPark();
      const outs = [
        call(p, "scene", { w: 1000, h: 700, still: true }),
        call(p, "scene", { w: 390, h: 844, night: true, k: 2, still: true }),
        call(p, "world", plan("k1"), {}),
        call(p, "building", "library", "active", "research", 150, true),
        call(p, "agent", { role: "builder", expr: "walking" }, 90, false),
      ];
      for (const o of outs) expect(motionLeaks(o)).toEqual([]);
    },
  );
});

describe("WEB_1b_park_world: world(plan, { night, seed }) thumbnails", () => {
  describe.each(realPlans())("WEB_1b_park_world plan $name", ({ make }) => {
    for (const [label, opts] of [
      ["defaults", undefined],
      ["night", { night: true }],
      ["seed 9", { seed: 9 }],
      ["night and seed 1", { night: true, seed: 1 }],
    ] as const) {
      it(`WEB_1b_park_world_${label}`, SLOW, () => {
        const p = pair();
        const args = opts === undefined ? [make()] : [make(), opts];
        expect(both(p, "world", ...args)).toBeNull();
      });
    }
  });

  it("WEB_1b_park_world_the_rich_plan_day_and_night", SLOW, () => {
    for (const opts of [{}, { night: true }, { seed: 12, night: true }]) {
      expect(both(pair(), "world", richPlan(), opts), JSON.stringify(opts)).toBeNull();
    }
  });

  it("WEB_1b_park_world_is_an_img_with_object_fit_contain_and_an_svg_source", () => {
    const img = canon(call(portPark(), "world", plan("fresh"), {})) as {
      tag: string;
      props: Record<string, Json>;
    };
    expect(img.tag).toBe("img");
    expect(String(img.props.src)).toMatch(
      /^blob:image\/svg\+xml\|<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg"/,
    );
    expect((img.props.style as Record<string, Json>).objectFit).toBe("contain");
    expect(img.props.alt).toBe("");
  });
});

describe("WEB_1b_park_building and WEB_1b_park_agent: solo art in day and night", () => {
  describe.each(kitKeys)("WEB_1b_park_building kit %s", (key) => {
    it("WEB_1b_park_building_every_state_day_and_night", SLOW, () => {
      const p = pair();
      for (const state of BUILDING_STATES) {
        for (const night of [false, true]) {
          expect(
            both(p, "building", key, state, "research", 150, night),
            `${key}/${state}/${night}`,
          ).toBeNull();
          expect(
            both(p, "building", key, state, undefined, undefined, night),
            `${key}/${state}/${night}/defaults`,
          ).toBeNull();
        }
      }
    });
  });

  it("WEB_1b_park_building_object_specs_like_the_inbox_row_and_dist_tints", () => {
    const p = pair();
    const spec = { fp: [2, 1], fl: 1, roof: "flat", fa: "windows", i: "mail" };
    for (const d of ["mail", "delivery", "analysis", "no-such-district", undefined]) {
      expect(both(p, "building", spec, "idle", d, 120, false), `${d}`).toBeNull();
      expect(both(p, "building", spec, "active", d, 120, true), `${d} night`).toBeNull();
    }
  });

  it("WEB_1b_park_building_is_an_img_with_the_width_and_height_read_back_from_the_svg", () => {
    const img = canon(
      call(portPark(), "building", "library", "active", "research", 150, false),
    ) as {
      tag: string;
      props: Record<string, Json>;
    };
    expect(img.tag).toBe("img");
    expect(typeof img.props.width).toBe("number");
    expect(typeof img.props.height).toBe("number");
    expect(img.props.height).toBe(150);
    expect(img.props.draggable).toBe(false);
  });

  describe.each(roleKeys)("WEB_1b_park_agent role %s", (role) => {
    it("WEB_1b_park_agent_expressions_ranks_sizes_day_and_night", SLOW, () => {
      const p = pair();
      for (const expr of EXPRESSIONS) {
        for (const rank of ["director", "lead", undefined]) {
          for (const night of [false, true]) {
            expect(
              both(p, "agent", { role, expr, rank }, 90, night),
              `${role}/${expr}/${rank}/${night}`,
            ).toBeNull();
          }
        }
      }
      expect(both(p, "agent", { role, expr: "needs" }, undefined, false)).toBeNull();
      expect(both(p, "agent", { role, expr: "needs" }, 36, true)).toBeNull();
      expect(both(p, "agent", { role }, 140)).toBeNull();
    });
  });
});

describe("WEB_1b_park_determinism: the seeded rng stays; no clock, no Math.random", () => {
  it("WEB_1b_park_determinism_scene_twice_and_on_two_instances_is_equal", SLOW, () => {
    const o = { w: 900, h: 600, seed: 31, night: true };
    const first = call(portPark(), "scene", o);
    const again = call(portPark(), "scene", o);
    const p = portPark();
    expect(sameAsPrototype(call(p, "scene", o), first)).toBeNull();
    expect(sameAsPrototype(call(p, "scene", o), first), "same instance, second call").toBeNull();
    expect(sameAsPrototype(again, first)).toBeNull();
  });

  it("WEB_1b_park_determinism_never_reads_the_clock_or_Math_random", SLOW, () => {
    vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("Math.random was called");
    });
    vi.spyOn(Date, "now").mockImplementation(() => {
      throw new Error("Date.now was called");
    });
    const p = portPark();
    call(p, "scene", { w: 600, h: 400, night: true });
    call(p, "scene", { w: 390, h: 844 });
    call(p, "world", richPlan(), { night: true });
    call(p, "building", "townhall", "needs", "hall", 150, true);
    call(p, "agent", { role: "tester", expr: "focused" }, 90, true);
  });

  it(
    "WEB_1b_park_determinism_property_scene_matches_the_prototype_for_any_seed_and_size",
    SLOW,
    () => {
      fc.assert(
        fc.property(
          fc.integer({ min: 0, max: 2 ** 31 }),
          fc.integer({ min: 320, max: 700 }),
          fc.integer({ min: 200, max: 500 }),
          fc.boolean(),
          fc.double({ min: 0, max: 1, noNaN: true }),
          (seed, w, h, night, mute) => bothScene(pair(), { w, h, seed, night, mute }) === null,
        ),
        { numRuns: 8 },
      );
    },
  );
});

describe("WEB_1b_park_env: browser calls go through the injectable env, never a window global", () => {
  it(
    "WEB_1b_park_env_every_image_source_comes_from_env_createObjectURL_with_an_svg_blob",
    SLOW,
    () => {
      const blobs: { type: string; text: string }[] = [];
      class SpyBlob {
        readonly text: string;
        readonly type: string;
        constructor(parts: unknown[], opts?: { type?: string }) {
          this.text = parts.map(String).join("");
          this.type = opts?.type ?? "";
        }
      }
      const env = {
        Blob: SpyBlob,
        createObjectURL: (b: SpyBlob) => {
          blobs.push({ type: b.type, text: b.text });
          return `spy://${blobs.length}`;
        },
      };
      const r = call(portPark(env), "scene", { w: 500, h: 360 }) as { el: unknown };
      expect(blobs.length).toBeGreaterThan(10);
      expect(new Set(blobs.map((b) => b.type))).toEqual(new Set(["image/svg+xml"]));
      for (const b of blobs) expect(b.text.startsWith("<svg")).toBe(true);
      const text = JSON.stringify(canon(r.el));
      expect(text).toContain("spy://1");
      expect(text).not.toContain("blob:");
    },
  );

  it("WEB_1b_park_env_only_createObjectURL_given_a_real_Blob_is_passed_to_it", () => {
    const seen: { isBlob: boolean; type: string; size: number }[] = [];
    const env = {
      createObjectURL: (b: Blob) => {
        seen.push({ isBlob: b instanceof Blob, type: b.type, size: b.size });
        return "x://img";
      },
    };
    const img = canon(call(portPark(env), "world", plan("fresh"), {})) as {
      props: Record<string, Json>;
    };
    expect(img.props.src).toBe("x://img");
    expect(seen).toHaveLength(1);
    expect(seen[0]?.isBlob).toBe(true);
    expect(seen[0]?.type).toBe("image/svg+xml");
    expect(seen[0]?.size).toBeGreaterThan(100);
  });

  it("WEB_1b_park_env_defaults_work_in_plain_node_without_a_window", () => {
    expect(typeof (globalThis as { window?: unknown }).window).toBe("undefined");
    const made: string[] = [];
    const park = (createPark as unknown as MakePark)(serialiseH, createWorld);
    const img = canon(call(park, "building", "library", "active", "research", 100, false)) as {
      props: Record<string, Json>;
    };
    const src = String(img.props.src);
    made.push(src);
    expect(src).toMatch(/^blob:/);
    URL.revokeObjectURL(src);
  });

  it("WEB_1b_park_env_creating_and_using_the_park_sets_no_global", () => {
    const before = new Set(Object.getOwnPropertyNames(globalThis));
    const park = portPark();
    call(park, "scene", { w: 400, h: 300 });
    call(park, "world", plan("fresh"), {});
    const added = Object.getOwnPropertyNames(globalThis).filter((k) => !before.has(k));
    expect(added).toEqual([]);
    expect((globalThis as Record<string, unknown>).TiloWorld).toBeUndefined();
    expect((globalThis as Record<string, unknown>).TiloPark).toBeUndefined();
  });

  it(
    "WEB_1b_park_env_the_world_factory_is_used_with_the_parks_own_string_builder_not_the_callers_h",
    SLOW,
    () => {
      // The caller's h must only ever see the park's own elements (div, img), never svg internals:
      // the SVG art is written as text into the blobs.
      const tags = new Set<string>();
      const h: TestH = (tag, props, ...children) => {
        tags.add(tag);
        return serialiseH(tag, props, ...children);
      };
      call(portPark(fakeEnv, h), "scene", { w: 500, h: 360 });
      call(portPark(fakeEnv, h), "world", plan("fresh"), {});
      call(portPark(fakeEnv, h), "agent", { role: "builder" }, 90, false);
      expect([...tags].sort()).toEqual(["div", "img"]);
    },
  );
});
