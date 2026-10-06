// WEB-1c (docs/web-app-rebuild-plan.md sections 2, 5, 8a, 9; ADR-0003a 3): the TypeScript port of the
// prototype's render kit (`kit(h)` and its icon table `X` in tilo-app.js) is the prototype, tree for tree.
// The prototype runs in a Node vm (test-support/park/kitProto.ts: tilo-world.js and tilo-park.js as
// window.TiloWorld / window.TiloPark, the prototype's own `D`, fake Blob and URL.createObjectURL); the port
// `createKit(h, { plans, env })` runs with the same serialising `h`, the same inputs and the same fakes.
// The comparison is the WEB-1b one: `sameAsPrototype(port, proto, { frozenWalkers: true })` (WEB-1b draws
// movers frozen, no animation; WEB-3 restores motion), so there is one reference construction, not two.
//
// Pinned decisions (each is listed in the WEB-1c report):
//  - createKit(h, deps): deps.plans is the prototype's `D.plans` (the plan source), deps.env is the
//    optional ParkEnv. W = createWorld(h) and TP = createPark(h, createWorld, deps.env).
//  - The prototype's `ready()` only checks that two window globals exist. The port has no globals, so it
//    has no `ready` and nothing here pins one.
import * as fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import {
  DEC_COMBOS,
  EXPRESSIONS,
  PLAN_IDS,
  RANKS,
  richPlan,
} from "../../../test-support/park/engineCases";
import {
  type Engine,
  call,
  canon,
  fakeEnv,
  protoIconNames,
  protoPlans,
  protoWorld,
  sameAsPrototype,
  serialiseH,
  size,
} from "../../../test-support/park/engineProto";
import {
  KIT_MEMBERS,
  type Kit,
  type KitDeps,
  type MakeKit,
  nodesOf,
  protoKit,
  protoKitIconNames,
  protoKitWithData,
  protoWorlds,
} from "../../../test-support/park/kitProto";
import { plans as fixturePlans } from "../api/fixtures";
import { ICON_NAMES, createKit } from "./kit";

const SLOW = { timeout: 180_000 };

/** The port, wired the way the app will wire it: the typed fixture plans and the fake browser calls. */
function portKit(): Kit {
  return (createKit as unknown as MakeKit)(serialiseH, {
    plans: fixturePlans as unknown as KitDeps["plans"],
    env: fakeEnv,
  });
}
const pair = () => ({ port: portKit(), proto: protoKit() });
const same = (port: unknown, proto: unknown): string | null =>
  sameAsPrototype(port, proto, { frozenWalkers: true });

const roleKeys = Object.keys(protoWorld().ROLE as object);
const kitKeys = Object.keys(protoWorld().KIT as object);

describe("WEB_1c_surface: createKit(h, deps) returns what kit(h) returns", () => {
  it("WEB_1c_surface_exactly_the_members_W_TP_ck_icon_agent_building_world_art_strip", () => {
    const { port, proto } = pair();
    expect(Object.keys(port).sort()).toEqual(KIT_MEMBERS);
    expect(Object.keys(proto).sort()).toEqual(KIT_MEMBERS);
    for (const m of ["ck", "icon", "agent", "building", "world", "art", "strip"])
      expect(typeof (port as unknown as Record<string, unknown>)[m], m).toBe("function");
    expect(typeof port.W).toBe("object");
    expect(typeof port.TP).toBe("object");
  });

  it("WEB_1c_surface_W_is_a_world_engine_with_the_prototype_members", () => {
    const { port, proto } = pair();
    expect(Object.keys(port.W).sort()).toEqual(Object.keys(proto.W).sort());
    expect(Object.keys(port.W)).toEqual(expect.arrayContaining(["icon", "soloAgent", "world"]));
  });

  it("WEB_1c_surface_TP_is_a_park_engine_with_scene_world_building_agent", () => {
    const { port, proto } = pair();
    expect(Object.keys(port.TP).sort()).toEqual(["agent", "building", "scene", "world"]);
    expect(Object.keys(proto.TP).sort()).toEqual(["agent", "building", "scene", "world"]);
  });

  it("WEB_1c_surface_W_and_TP_draw_the_same_as_the_prototypes_own", SLOW, () => {
    const { port, proto } = pair();
    expect(
      same(
        call(port.W as Engine, "icon", "laptop", "currentColor", 0, 0, 0.9, "#FFFFFF"),
        call(proto.W as Engine, "icon", "laptop", "currentColor", 0, 0, 0.9, "#FFFFFF"),
      ),
    ).toBeNull();
    expect(
      same(
        call(port.TP as Engine, "building", "library", "active", "research", 150, true),
        call(proto.TP as Engine, "building", "library", "active", "research", 150, true),
      ),
    ).toBeNull();
    expect(
      same(
        call(port.TP as Engine, "agent", { role: "builder", expr: "focused" }, 90, false),
        call(proto.TP as Engine, "agent", { role: "builder", expr: "focused" }, 90, false),
      ),
    ).toBeNull();
  });
});

describe("WEB_1c_icon: icon(name, size) for the kit table X, the world fall-through and unknown names", () => {
  const fromTable = protoKitIconNames();
  const fromWorld = protoIconNames();
  // laptop, mail, coin and hall are kit icon names that the kit table does not hold: W.icon draws them.
  const fallThrough = ["laptop", "mail", "coin", "hall"];
  const names = [...new Set([...fromTable, ...fromWorld, ...fallThrough, "zz-no-such-icon"])];
  const SIZES = [undefined, 0, 12, 16, 20];

  it("WEB_1c_icon_the_reference_table_is_what_the_task_says_it_is", () => {
    expect(fromTable.length).toBeGreaterThanOrEqual(30);
    expect(fromTable).toEqual(expect.arrayContaining(["home", "grid", "globe", "bolt", "play"]));
    for (const n of fallThrough) expect(fromTable, n).not.toContain(n);
    for (const n of fallThrough) expect(fromWorld, n).toContain(n);
  });

  it("WEB_1c_icon_ICON_NAMES_is_the_names_of_the_prototypes_X_table_in_order", () => {
    expect([...ICON_NAMES]).toEqual(fromTable);
    expect(new Set(ICON_NAMES).size, "no duplicates").toBe(ICON_NAMES.length);
  });

  it.each(names)("WEB_1c_icon_%s_every_size_equals_the_prototype", (name) => {
    const { port, proto } = pair();
    for (const s of SIZES) {
      const a = port.icon(name, s);
      expect(same(a, proto.icon(name, s)), `${name}@${s}`).toBeNull();
      expect(size(a), `${name}@${s} is not empty`).toBeGreaterThan(4);
    }
  });

  it("WEB_1c_icon_is_a_20_by_20_svg_viewbox_with_size_default_16_and_aria_hidden", () => {
    const { port } = pair();
    for (const [s, px] of [
      [undefined, 16],
      [0, 16],
      [12, 12],
      [20, 20],
    ] as const) {
      const svg = canon(port.icon("home", s)) as {
        tag: string;
        props: Record<string, unknown>;
      };
      expect(svg.tag).toBe("svg");
      expect(svg.props.width, `width@${s}`).toBe(px);
      expect(svg.props.height, `height@${s}`).toBe(px);
      expect(svg.props.viewBox).toBe("-10 -10 20 20");
      expect(svg.props.style).toEqual({ display: "block", flex: "none" });
      expect(svg.props["aria-hidden"]).toBe(true);
    }
  });

  it("WEB_1c_icon_a_name_in_the_kit_table_is_drawn_from_it_not_from_the_world_engine", () => {
    // `play`, `plus`, `x` and others exist only in X; `laptop` only in W: they differ from each other.
    const { port } = pair();
    const play = JSON.stringify(canon(port.icon("play", 16)));
    expect(play).toContain("M-3 -5.5 L5 0 L-3 5.5 Z");
    expect(JSON.stringify(canon(port.icon("laptop", 16)))).not.toContain("M-3 -5.5 L5 0 L-3 5.5 Z");
  });

  it("WEB_1c_icon_every_table_name_draws_and_the_names_differ", () => {
    const { port } = pair();
    const drawn = new Set(fromTable.map((n) => JSON.stringify(canon(port.icon(n, 16)))));
    expect(drawn.size, "30 distinct icons").toBe(fromTable.length);
  });
});

describe("WEB_1c_agent: agent(a, size, night) = TP.agent, memoised", () => {
  describe.each(roleKeys)("WEB_1c_agent role %s", (role) => {
    it("WEB_1c_agent_expressions_ranks_sizes_day_and_night", SLOW, () => {
      const { port, proto } = pair();
      for (const expr of EXPRESSIONS) {
        for (const rank of RANKS.slice(0, 3)) {
          for (const night of [false, true]) {
            const a = { role, expr, rank };
            expect(
              same(port.agent(a, 90, night), proto.agent(a, 90, night)),
              `${role}/${expr}/${rank}/${night}`,
            ).toBeNull();
          }
        }
      }
      const a = { role, expr: "needs" };
      expect(same(port.agent(a, undefined, false), proto.agent(a, undefined, false))).toBeNull();
      expect(same(port.agent(a, 36, true), proto.agent(a, 36, true))).toBeNull();
      expect(same(port.agent({ role }, 140), proto.agent({ role }, 140))).toBeNull();
    });
  });

  it("WEB_1c_agent_is_an_image_not_an_empty_tree", () => {
    const img = canon(portKit().agent({ role: "builder", expr: "focused" }, 90, false)) as {
      tag: string;
    };
    expect(img.tag).toBe("img");
  });
});

describe("WEB_1c_building: building(spec, state, dist, ht, night) = TP.building, memoised", () => {
  const STATES = [
    "planned",
    "construction",
    "active",
    "needs",
    "complete",
    "idle",
    "skipped",
    "blocked",
  ];
  describe.each(kitKeys)("WEB_1c_building kit %s", (key) => {
    it("WEB_1c_building_every_state_day_and_night", SLOW, () => {
      const { port, proto } = pair();
      for (const state of STATES) {
        for (const night of [false, true]) {
          expect(
            same(
              port.building(key, state, "research", 150, night),
              proto.building(key, state, "research", 150, night),
            ),
            `${key}/${state}/${night}`,
          ).toBeNull();
          expect(
            same(
              port.building(key, state, undefined, undefined, night),
              proto.building(key, state, undefined, undefined, night),
            ),
            `${key}/${state}/${night}/defaults`,
          ).toBeNull();
        }
      }
    });
  });

  it("WEB_1c_building_gen_specs_like_the_inbox_row_and_every_district_tint", SLOW, () => {
    const { port, proto } = pair();
    const specs = [
      { fp: [2, 1], fl: 1, roof: "flat", fa: "windows", i: "mail" },
      { name: "Laptop Depot", fp: [2, 1], i: "laptop" },
      { name: "Launch Kit", fp: [1, 1], i: "doc" },
    ];
    for (const spec of specs) {
      for (const d of [
        "mail",
        "delivery",
        "analysis",
        "research",
        "hall",
        "no-such-district",
        undefined,
      ]) {
        for (const state of ["idle", "active", "needs", "planned"]) {
          for (const night of [false, true]) {
            expect(
              same(
                port.building(spec, state, d, 120, night),
                proto.building(spec, state, d, 120, night),
              ),
              `${JSON.stringify(spec)}/${d}/${state}/${night}`,
            ).toBeNull();
          }
        }
      }
    }
  });

  it("WEB_1c_building_is_an_img_with_the_height_given", () => {
    const img = canon(portKit().building("library", "active", "research", 150, false)) as {
      tag: string;
      props: Record<string, unknown>;
    };
    expect(img.tag).toBe("img");
    expect(img.props.height).toBe(150);
  });
});

describe("WEB_1c_world: world(planId, dec, night) = TP.world(D.plans(dec)[planId], { night }), memoised", () => {
  const protoPlanIds = Object.keys(protoPlans({}));

  it("WEB_1c_world_the_plan_ids_are_k1_hires_audit_fresh", () => {
    expect(protoPlanIds).toEqual([...PLAN_IDS]);
  });

  describe.each(DEC_COMBOS)("WEB_1c_world decisions $name", ({ dec }) => {
    it.each([...PLAN_IDS])("WEB_1c_world_plan_%s_day_and_night", SLOW, (planId) => {
      const { port, proto } = pair();
      for (const night of [false, true]) {
        const a = port.world(planId, dec, night);
        expect(same(a, proto.world(planId, dec, night)), `${planId}/${night}`).toBeNull();
        expect(size(a), `${planId} is a real picture`).toBeGreaterThan(5);
      }
    });
  });

  it("WEB_1c_world_no_decisions_at_all_equals_the_prototype_for_every_plan", SLOW, () => {
    const { port, proto } = pair();
    for (const planId of PLAN_IDS) {
      for (const dec of [undefined, {}]) {
        expect(same(port.world(planId, dec), proto.world(planId, dec)), `${planId}`).toBeNull();
        expect(
          same(port.world(planId, dec, true), proto.world(planId, dec, true)),
          `${planId}/night`,
        ).toBeNull();
      }
    }
  });

  it(
    "WEB_1c_world_the_four_k1_decision_pictures_all_differ_and_the_key_rule_keeps_them_apart",
    SLOW,
    () => {
      const { port, proto } = pair();
      const trees = DEC_COMBOS.map((c) => JSON.stringify(canon(port.world("k1", c.dec, false))));
      expect(new Set(trees).size, "four distinct k1 pictures").toBe(4);
      // asked in a different order, still each its own: the key rule is k1 + depot + mail
      for (const c of [...DEC_COMBOS].reverse()) {
        expect(
          same(port.world("k1", c.dec, false), proto.world("k1", c.dec, false)),
          c.name,
        ).toBeNull();
      }
    },
  );

  it(
    "WEB_1c_world_the_plans_come_from_deps_plans_and_the_world_is_drawn_on_the_given_plan",
    SLOW,
    () => {
      const proto = protoKit();
      const asked: unknown[] = [];
      const rich = richPlan();
      const port = (createKit as unknown as MakeKit)(serialiseH, {
        plans: (dec) => {
          asked.push(dec);
          return { custom: rich };
        },
        env: fakeEnv,
      });
      for (const night of [false, true]) {
        expect(
          same(
            port.world("custom", { depot: true }, night),
            call(proto.TP as Engine, "world", richPlan(), { night }),
          ),
          `custom/${night}`,
        ).toBeNull();
      }
      expect(asked).toEqual([{ depot: true }, { depot: true }]);
    },
  );
});

describe("WEB_1c_art_strip: art(w, ht, night) and strip(w, ht, night) on the prototype's own worlds", () => {
  const worlds = protoWorlds({});

  it("WEB_1c_art_strip_the_reference_worlds_cover_single_row_and_neither", () => {
    expect(worlds.filter((w) => w.single).length).toBeGreaterThanOrEqual(2);
    expect(worlds.filter((w) => w.row).length).toBeGreaterThanOrEqual(2);
    expect(worlds.filter((w) => !w.single && !w.row).length).toBeGreaterThanOrEqual(2);
    expect(
      worlds.some((w) => JSON.stringify(w.row ?? "").includes('"fp"')),
      "a row with an inline generated building",
    ).toBe(true);
  });

  it("WEB_1c_art_equals_the_prototype_for_every_world_height_and_light", SLOW, () => {
    const { port, proto } = pair();
    for (const w of worlds) {
      for (const ht of [undefined, 150, 90]) {
        for (const night of [undefined, false, true]) {
          const a = port.art(w, ht, night);
          expect(same(a, proto.art(w, ht, night)), `${String(w.id)}/${ht}/${night}`).toBeNull();
          if (w.single || w.row) expect(a, `${String(w.id)} has art`).not.toBeNull();
          else expect(a, `${String(w.id)} has none`).toBeNull();
        }
      }
    }
  });

  it("WEB_1c_strip_equals_the_prototype_for_every_world_height_and_light", SLOW, () => {
    const { port, proto } = pair();
    let strips = 0;
    for (const w of worlds) {
      for (const ht of [undefined, 150, 90]) {
        for (const night of [undefined, false, true]) {
          const a = port.strip(w, ht, night);
          expect(same(a, proto.strip(w, ht, night)), `${String(w.id)}/${ht}/${night}`).toBeNull();
          if (w.row) {
            strips++;
            expect(Array.isArray(a)).toBe(true);
          } else {
            expect(a, `${String(w.id)} has no row`).toBeNull();
          }
        }
      }
    }
    expect(strips).toBeGreaterThan(5);
  });

  it("WEB_1c_strip_each_slot_is_a_div_keyed_by_its_index_with_margin_minus_14_after_the_first", () => {
    const { port } = pair();
    const row = worlds.find((w) => Array.isArray(w.row) && (w.row as unknown[]).length >= 2);
    expect(row, "a world with a row of two or more").toBeDefined();
    const slots = port.strip(row as ArtWorldLike, 150, false) as {
      tag: string;
      props: { key: number; style: { marginLeft: number } };
      children: unknown[];
    }[];
    expect(slots).toHaveLength((row?.row as unknown[]).length);
    slots.forEach((s, i) => {
      expect(s.tag).toBe("div");
      expect(s.props.key).toBe(i);
      expect(s.props.style.marginLeft).toBe(i ? -14 : 0);
      expect(s.children).toHaveLength(1);
      expect(nodesOf(s.children)[0]?.tag).toBe("img");
    });
  });
});

type ArtWorldLike = Parameters<Kit["art"]>[0];

describe("WEB_1c_memo_parity: the memoisation behaves as the prototype's, call for call", () => {
  /** For each result, the index of the first earlier call that returned the identical object. */
  const identityPattern = (rs: unknown[]): number[] => rs.map((r) => rs.findIndex((x) => x === r));
  const SEQUENCE: ((k: Kit) => unknown)[] = [
    (k) => k.agent({ role: "builder", expr: "focused" }, 90, false), // 0
    (k) => k.agent({ role: "builder", expr: "focused" }, 90, false), // 1 = 0 (key is the content)
    (k) => k.agent({ role: "builder", expr: "focused" }, 90, true), // 2 new (night)
    (k) => k.agent({ role: "builder", expr: "focused" }, 90), // 3 = 0 (undefined night is day)
    (k) => k.agent({ role: "builder", expr: "focused" }, 36, false), // 4 new (size)
    (k) => k.agent({ expr: "focused", role: "builder" }, 90, false), // 5 new (key order is the key)
    (k) => k.building("library", "active", "research", 150, false), // 6
    (k) => k.building("library", "active", "research", 150, undefined), // 7 = 6
    (k) => k.building("library", "active", "research", 150, true), // 8 new
    (k) => k.building("library", "active", "research1", 50, false), // 9 = 6 (the key has no separators)
    (k) => k.world("k1", { depot: true, mail: false }, false), // 10
    (k) => k.world("k1", { depot: true }, false), // 11 = 10
    (k) => k.world("k1", {}, false), // 12 new
    (k) => k.world("k1", undefined, false), // 13 = 12
    (k) => k.world("hires", { depot: true }, false), // 14
    (k) => k.world("hires", { depot: true, mail: false }, false), // 15 = 14 (same decision flags)
    (k) => k.world("hires", { mail: true }, true), // 16 new (night)
    (k) => k.art({ single: ["library", "active", "research"] }, 150, false), // 17 = 6
    (k) =>
      k.art(
        {
          row: [
            ["library", "active", "research"],
            ["dock", "idle", "delivery"],
          ],
        },
        150,
        false,
      ), // 18 = 6
    (k) =>
      k.strip(
        {
          row: [
            ["library", "active", "research"],
            ["dock", "idle", "delivery"],
          ],
        },
        150,
        false,
      ), // 19 new
    (k) => k.icon("home", 16), // 20 never cached
    (k) => k.icon("home", 16), // 21 new again
    (k) => k.ck("sentinel", () => ({ a: 1 })), // 22
    (k) => k.ck("sentinel", () => ({ a: 2 })), // 23 = 22
  ];

  it(
    "WEB_1c_memo_parity_equal_calls_return_the_same_object_exactly_where_the_prototype_does",
    SLOW,
    () => {
      const { port, proto } = pair();
      const a = SEQUENCE.map((f) => f(port));
      const b = SEQUENCE.map((f) => f(proto));
      expect(identityPattern(a)).toEqual(identityPattern(b));
      // the pattern is not vacuous: calls 1, 3, 7, 9, 11, 13, 15, 17, 18, 23 return an earlier object
      expect(identityPattern(b).filter((v, i) => v !== i).length).toBeGreaterThanOrEqual(10);
      a.forEach((r, i) => expect(same(r, b[i]), `call ${i}`).toBeNull());
    },
  );
});

describe("WEB_1c_invariants: properties of the kit", () => {
  it("WEB_1c_property_any_agent_call_sequence_has_the_prototypes_identity_pattern", SLOW, () => {
    const call1 = fc.tuple(
      fc.constantFrom("builder", "tester", "research"),
      fc.constantFrom(undefined, 36, 90),
      fc.constantFrom(undefined, false, true),
    );
    fc.assert(
      fc.property(fc.array(call1, { minLength: 1, maxLength: 8 }), (calls) => {
        const { port, proto } = pair();
        const run = (k: Kit) => calls.map(([role, s, night]) => k.agent({ role }, s, night));
        const a = run(port);
        const b = run(proto);
        const pat = (rs: unknown[]) => rs.map((r) => rs.findIndex((x) => x === r));
        return (
          JSON.stringify(pat(a)) === JSON.stringify(pat(b)) &&
          a.every((r, i) => same(r, b[i]) === null)
        );
      }),
      { numRuns: 12 },
    );
  });

  it("WEB_1c_invariants_creating_and_using_the_kit_sets_no_global_and_needs_no_window", () => {
    expect(typeof (globalThis as { window?: unknown }).window).toBe("undefined");
    const before = new Set(Object.getOwnPropertyNames(globalThis));
    const k = portKit();
    k.icon("home", 16);
    k.agent({ role: "builder" }, 90, false);
    k.building("library", "active", "research", 100, false);
    k.world("fresh", {}, false);
    const added = Object.getOwnPropertyNames(globalThis).filter((n) => !before.has(n));
    expect(added).toEqual([]);
    expect((globalThis as Record<string, unknown>).TiloApp).toBeUndefined();
    expect((globalThis as Record<string, unknown>).TiloWorld).toBeUndefined();
    expect((globalThis as Record<string, unknown>).TiloPark).toBeUndefined();
  });

  it("WEB_1c_invariants_never_reads_the_clock_or_Math_random", SLOW, () => {
    vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("Math.random was called");
    });
    vi.spyOn(Date, "now").mockImplementation(() => {
      throw new Error("Date.now was called");
    });
    try {
      const k = portKit();
      k.icon("laptop", 16);
      k.agent({ role: "tester", expr: "focused" }, 90, true);
      k.building("townhall", "needs", "hall", 150, true);
      k.world("k1", { depot: true, mail: true }, true);
      k.strip(
        {
          row: [
            ["desk", "idle", "mail"],
            ["dock", "active", "delivery"],
          ],
        },
        100,
        false,
      );
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("WEB_1c_invariants_defaults_work_in_plain_node_with_no_env", () => {
    const k = (createKit as unknown as MakeKit)(serialiseH, {
      plans: fixturePlans as unknown as KitDeps["plans"],
    });
    const img = canon(k.building("library", "active", "research", 100, false)) as {
      props: Record<string, unknown>;
    };
    const src = String(img.props.src);
    expect(src).toMatch(/^blob:/);
    URL.revokeObjectURL(src);
  });

  it("WEB_1c_invariants_the_reference_data_is_the_ports_data", () => {
    // The port is wired to the typed fixtures; the prototype to its own D. They draw the same plans.
    const { data } = protoKitWithData();
    for (const c of DEC_COMBOS) {
      expect(JSON.stringify(canon(fixturePlans(c.dec as never)))).toEqual(
        JSON.stringify(canon(JSON.parse(JSON.stringify(data.plans(c.dec))))),
      );
    }
  });
});
