// WEB-1b (docs/web-app-rebuild-plan.md sections 2, 5, 9 BQ-WEB-5; ADR-0003a 3): the TypeScript port of
// tilo-world.js is the prototype, tree for tree. design_handoff_tilo_web_app/design/tilo-world.js runs in
// a Node vm with a stub `window` (test-support/park/engineProto.ts); createWorld(h) from ./world runs with
// the same serialising `h` and the same inputs; the two trees must be identical (numbers exact).
//
// One deliberate difference, pinned here: WEB-1b adds no animation (plan section 6, BQ-WEB-3, ADR-0003a 5:
// "WEB-1 to WEB-2 add no keyframes"). The prototype's `anim` option (world, metro) and `anim` style
// string (pin, agent) are accepted and ignored: the port with anim on equals the prototype with anim off.
// The prototype's `anim` defaults to on, so the port's defaults equal the prototype's `anim: false`.
import * as fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BUILDING_STATES,
  EXPRESSIONS,
  METRO_OPTION_SETS,
  RANKS,
  metroLevels,
  plan,
  realPlans,
  richPlan,
  worldOptionSets,
} from "../../../test-support/park/engineCases";
import {
  type Engine,
  call,
  canon,
  motionLeaks,
  protoIconNames,
  protoWorld,
  sameAsPrototype,
  serialiseH,
  size,
} from "../../../test-support/park/engineProto";
import { createWorld } from "./world";

const MEMBERS = [
  "metro",
  "world",
  "soloBuilding",
  "soloAgent",
  "soloPiece",
  "layout",
  "KIT",
  "DIST",
  "ROLE",
  "K0",
  "icon",
  "dk",
  "lt",
  "agent",
  "pin",
  "tag",
  "label",
  "box",
  "poly",
  "shade",
  "crate",
  "P",
  "pts",
  "mL",
  "mR",
  "mT",
  "route",
  "along",
  "standOf",
  "gate",
  "clouds",
  "liftEl",
  "landing",
  "building",
  "specOf",
  "presence",
  "comment",
  "tree",
  "T",
  "G",
  "INS",
  "AS",
] as const;

const SLOW = { timeout: 120_000 };

function pair() {
  return { port: createWorld(serialiseH) as unknown as Engine, proto: protoWorld() };
}
type Pair = ReturnType<typeof pair>;

/** Same call on both engines; null when the trees are identical, else where they first differ. */
function both(p: Pair, name: string, ...args: unknown[]): string | null {
  return sameAsPrototype(call(p.port, name, ...args), call(p.proto, name, ...args));
}

const kitKeys = Object.keys(protoWorld().KIT as object);
const roleKeys = Object.keys(protoWorld().ROLE as object);

afterEach(() => {
  vi.restoreAllMocks();
});

describe("WEB_1b_world_surface: createWorld(h) returns what TiloWorld(h) returns", () => {
  it("WEB_1b_world_surface_has_exactly_the_prototype_members", () => {
    const port = createWorld(serialiseH) as unknown as Engine;
    expect(Object.keys(port).sort()).toEqual([...MEMBERS].sort());
    expect(Object.keys(protoWorld()).sort(), "the prototype member list moved").toEqual(
      [...MEMBERS].sort(),
    );
  });

  it.each(["KIT", "DIST", "ROLE", "K0", "T", "G", "INS", "AS"] as const)(
    "WEB_1b_world_surface_constant_%s_equals_the_prototype",
    (name) => {
      const p = pair();
      expect(sameAsPrototype(p.port[name], p.proto[name])).toBeNull();
    },
  );

  it("WEB_1b_world_surface_constants_are_not_vacuous", () => {
    const p = protoWorld();
    expect(Object.keys(p.KIT as object)).toHaveLength(14);
    expect(Object.keys(p.ROLE as object)).toContain("research");
    expect((p.K0 as Record<string, unknown>).hero).toBe("#5A3FE0");
    expect(p.T).toBe(48);
  });

  it("WEB_1b_world_surface_every_function_member_is_a_function", () => {
    const port = createWorld(serialiseH) as unknown as Engine;
    for (const m of MEMBERS) {
      if (/^[A-Z]+[0-9]?$/.test(m) && m !== "P") continue; // constants
      expect(typeof port[m], m).toBe("function");
    }
  });
});

describe("WEB_1b_world_matrix: world(plan, opts)", () => {
  const prototypeNotEmpty = () => {
    const p = protoWorld();
    return size(call(p, "world", plan("k1", { depot: true, mail: true }), { seed: 1 }));
  };

  it("WEB_1b_world_matrix_reference_tree_is_large_enough_to_mean_something", () => {
    expect(prototypeNotEmpty()).toBeGreaterThan(5000);
  });

  describe.each(realPlans())("WEB_1b_world_matrix plan $name", ({ make }) => {
    for (const set of worldOptionSets(make())) {
      it(`WEB_1b_world_matrix_${set.name}`, SLOW, () => {
        const p = pair();
        // anim is left out of the option sets: it has its own test below.
        const opts = { ...set.opts, anim: false };
        expect(both(p, "world", make(), opts)).toBeNull();
      });
    }
  });

  describe("WEB_1b_world_matrix the rich plan (routes, gates, presence, comments, locks, wraps)", () => {
    for (const set of worldOptionSets(richPlan())) {
      it(`WEB_1b_world_matrix_rich_${set.name}`, SLOW, () => {
        const p = pair();
        expect(both(p, "world", richPlan(), { ...set.opts, anim: false })).toBeNull();
      });
    }

    it("WEB_1b_world_matrix_rich_plan_reaches_routes_and_pins_in_the_reference", () => {
      const text = JSON.stringify(canon(call(protoWorld(), "world", richPlan(), { anim: false })));
      expect(text).toContain("M"); // route paths are drawn
      expect(text).toContain("AM"); // presence
      expect(text).toContain("Payroll"); // the locked district's tag
    });
  });

  it("WEB_1b_world_matrix_no_options_object_at_all", SLOW, () => {
    const p = pair();
    // The prototype defaults anim to on; the port ignores anim, so compare with anim off.
    expect(
      sameAsPrototype(
        call(p.port, "world", plan("fresh")),
        call(p.proto, "world", plan("fresh"), { anim: false }),
      ),
    ).toBeNull();
  });

  it("WEB_1b_world_matrix_parts_true_returns_ground_objs_cover_top_L_M_bb", SLOW, () => {
    for (const make of [() => plan("k1", { depot: true }), richPlan]) {
      for (const stage of [1, 2, 3, 4]) {
        const p = pair();
        expect(both(p, "world", make(), { parts: true, seed: 5, stage, anim: false })).toBeNull();
      }
    }
    const parts = call(pair().port, "world", plan("k1"), { parts: true }) as Record<
      string,
      unknown
    >;
    expect(Object.keys(parts).sort()).toEqual(["L", "M", "bb", "cover", "ground", "objs", "top"]);
  });
});

describe("WEB_1b_world_metro: stacked levels, lifts, satellites, bridges", () => {
  it.each(METRO_OPTION_SETS.map((s) => [s.name, s.opts] as const))(
    "WEB_1b_world_metro_%s",
    SLOW,
    (_n, opts) => {
      const p = pair();
      const args = opts === undefined ? [metroLevels()] : [metroLevels(), { ...opts, anim: false }];
      expect(both(p, "metro", ...args)).toBeNull();
    },
  );

  it("WEB_1b_world_metro_one_level_and_lift_states", SLOW, () => {
    const levels = () => [{ name: "Only", code: "L1", plan: plan("audit") }];
    expect(both(pair(), "metro", levels(), { anim: false })).toBeNull();
    const two = () => [
      {
        name: "A",
        code: "L1",
        plan: plan("fresh"),
        lifts: [
          { t: 1, state: "idle" },
          { t: 0.5, state: "active", parcel: true, label: "Box" },
        ],
      },
      { name: "B", code: "L2", plan: plan("audit"), stage: 2 },
    ];
    expect(both(pair(), "metro", two(), { anim: false })).toBeNull();
  });

  it("WEB_1b_world_metro_reference_tree_is_large_enough_to_mean_something", () => {
    expect(size(call(protoWorld(), "metro", metroLevels(), { anim: false }))).toBeGreaterThan(8000);
  });
});

describe("WEB_1b_world_solo: sheet renders", () => {
  describe.each(kitKeys)("WEB_1b_world_solo_building kit %s", (key) => {
    it("WEB_1b_world_solo_building_every_state_by_name_and_by_spec", SLOW, () => {
      const kit = (protoWorld().KIT as Record<string, unknown>)[key];
      for (const state of BUILDING_STATES) {
        const p = pair();
        expect(
          both(p, "soloBuilding", key, state, { d: "research", height: 150 }),
          `${key}/${state} by name`,
        ).toBeNull();
        expect(
          both(p, "soloBuilding", kit, state, { pin: true }),
          `${key}/${state} spec + pin`,
        ).toBeNull();
        expect(
          both(p, "soloBuilding", key, state, { cloud: true, tint: "#D9588C", height: 90 }),
          `${key}/${state} cloud`,
        ).toBeNull();
        expect(both(p, "soloBuilding", key, state), `${key}/${state} no options`).toBeNull();
      }
    });
  });

  it("WEB_1b_world_solo_building_generated_specs_like_Laptop_Depot", SLOW, () => {
    const gens = [
      { name: "Laptop Depot", fp: [2, 1], i: "laptop" },
      { name: "Mail Room", fp: [2, 1], i: "mail" },
      { name: "Launch Kit", fp: [1, 1], i: "doc" },
      { name: "Account Setup", fp: [2, 1], i: "person" },
      { name: "Training Hall", fp: [2, 2], i: "cap" },
      { name: "Mystery Annex" },
    ];
    for (const g of gens) {
      for (const seed of [1, 2, 3]) {
        const p = pair();
        const spec = call(p.proto, "specOf", { gen: g }, seed);
        for (const state of BUILDING_STATES) {
          expect(
            both(p, "soloBuilding", spec, state, { d: "mail", height: 150 }),
            `${g.name}/${seed}/${state}`,
          ).toBeNull();
        }
      }
    }
  });

  describe.each(roleKeys)("WEB_1b_world_solo_agent role %s", (role) => {
    it("WEB_1b_world_solo_agent_every_expression_and_rank", SLOW, () => {
      const p = pair();
      for (const expr of EXPRESSIONS) {
        for (const rank of RANKS) {
          const a = { role, expr, rank };
          expect(both(p, "soloAgent", a), `${role}/${expr}/${rank}`).toBeNull();
        }
      }
    });
  });

  it("WEB_1b_world_solo_agent_sizes_facing_and_extras", SLOW, () => {
    const p = pair();
    for (const size_ of [undefined, 40, 90, 140]) {
      expect(
        both(p, "soloAgent", { role: "builder", expr: "needs", rank: "lead" }, size_),
        `size ${size_}`,
      ).toBeNull();
    }
    const extras: Record<string, unknown>[] = [
      { role: "research", facing: "R" },
      { role: "delivery", expr: "walking", back: true },
      { role: "delivery", expr: "walking", step: true },
      { role: "tester", ring: true, expr: "needs" },
      { role: "builder", pack: true },
      { role: "connector", parcel: true },
      { role: "unknown-role" },
      { role: "builder", expr: "no-such-expression" },
      { rank: "director" },
      {},
    ];
    for (const a of extras) expect(both(p, "soloAgent", a), JSON.stringify(a)).toBeNull();
  });

  it.each([
    "plot",
    "road",
    "walk",
    "memory",
    "handoff",
    "gate-open",
    "gate-waiting",
    "gate-closed",
    "cloud",
    "island",
  ])("WEB_1b_world_solo_piece_%s", (kind) => {
    const p = pair();
    expect(both(p, "soloPiece", kind), "default size").toBeNull();
    expect(both(p, "soloPiece", kind, 130)).toBeNull();
    expect(both(p, "soloPiece", kind, 220)).toBeNull();
  });
});

describe("WEB_1b_world_primitives: icons, colours, projection, shapes, pins, tags", () => {
  it("WEB_1b_world_icon_names_list_matches_the_prototype_source", () => {
    const names = protoIconNames();
    expect(names.length).toBeGreaterThanOrEqual(30);
    expect(names).toContain("laptop");
    expect(names).toContain("up");
  });

  it("WEB_1b_world_icon_every_name_and_the_fallback", () => {
    const p = pair();
    for (const n of [...protoIconNames(), "no-such-icon"]) {
      expect(both(p, "icon", n, "#5A3FE0", 0, 0), `${n} min args`).toBeNull();
      expect(both(p, "icon", n, "#1F1D2B", 12.5, -7.25, 1.5, "#EEEBE2"), `${n} placed`).toBeNull();
    }
  });

  it("WEB_1b_world_dk_lt_over_colours_and_amounts", () => {
    const p = pair();
    for (const c of ["#ffffff", "#000000", "#5A3FE0", "#1F1D2B", "#a3b89d", "#F0A500", "7D8793"]) {
      for (const t of [undefined, null, 0, 0.07, 0.2, 0.5, 0.86, 1]) {
        expect(call(p.port, "dk", c, t), `dk ${c} ${t}`).toBe(call(p.proto, "dk", c, t));
        expect(call(p.port, "lt", c, t), `lt ${c} ${t}`).toBe(call(p.proto, "lt", c, t));
      }
    }
  });

  it("WEB_1b_world_projection_P_pts_mL_mR_mT", () => {
    const p = pair();
    const grid = [-120, -3.5, 0, 0.25, 48, 333.3333];
    for (const x of grid) {
      for (const y of grid) {
        for (const z of [undefined, 0, 3, 17.5, -26]) {
          expect(
            sameAsPrototype(call(p.port, "P", x, y, z), call(p.proto, "P", x, y, z)),
          ).toBeNull();
          for (const m of ["mL", "mR", "mT"]) {
            expect(call(p.port, m, x, y, z), `${m}(${x},${y},${z})`).toBe(
              call(p.proto, m, x, y, z),
            );
          }
        }
      }
    }
    const poly = [
      [0, 0],
      [10.123456, -2.5],
      [3, 4.999],
    ];
    expect(call(p.port, "pts", poly)).toBe(call(p.proto, "pts", poly));
    expect(call(p.port, "pts", [])).toBe(call(p.proto, "pts", []));
  });

  it("WEB_1b_world_shapes_box_poly_shade_crate", () => {
    const p = pair();
    const c = { t: "#EEEBE2", l: "#D3CDBD", r: "#BEB7A5" };
    expect(both(p, "box", 1, 2, 3, 40, 30, 20, c)).toBeNull();
    expect(
      both(p, "box", -5, 0, -26, 12.5, 7.5, 6, c, { opacity: 0.5, stroke: "none" }),
    ).toBeNull();
    const quad = [
      [0, 0],
      [10, 5],
      [0, 10],
      [-10, 5],
    ];
    expect(both(p, "poly", quad, "#BEB7A5")).toBeNull();
    expect(both(p, "poly", quad, "#BEB7A5", { strokeWidth: 2, strokeDasharray: "4 3" })).toBeNull();
    for (const col of ["#5A3FE0", "#2B98B5", "#ffffff"])
      expect(sameAsPrototype(call(p.port, "shade", col), call(p.proto, "shade", col))).toBeNull();
    expect(both(p, "crate", 4, 5, 0, 10)).toBeNull();
    expect(both(p, "crate", 4, 5, 8.5, 10, "#B48A52")).toBeNull();
  });

  it("WEB_1b_world_pin_every_kind_and_option", () => {
    const p = pair();
    const at = [120.5, 80.25];
    for (const kind of [
      "complete",
      "needs",
      "blocked",
      "fyi",
      "lock",
      "skipped",
      "active",
      "no-such-kind",
    ]) {
      expect(both(p, "pin", kind, at), `${kind} bare`).toBeNull();
      expect(both(p, "pin", kind, at, { lift: 16, r: 9 }), `${kind} small`).toBeNull();
      expect(both(p, "pin", kind, at, { count: "12" }), `${kind} count`).toBeNull();
      expect(
        both(p, "pin", kind, at, { icon: "mail", tint: "#D9588C", count: "3" }),
        `${kind} icon tint`,
      ).toBeNull();
    }
  });

  it("WEB_1b_world_tag_label_with_and_without_icon", () => {
    const p = pair();
    expect(both(p, "tag", "Firmware", [200, 100], "#2B98B5")).toBeNull();
    expect(both(p, "tag", "Laptop Depot", [200, 100], "#D7864F", "laptop")).toBeNull();
    expect(
      both(p, "tag", "Left aligned", [200, 100], "#6F8F8A", "mail", { left: true, fs: 12 }),
    ).toBeNull();
    expect(
      both(p, "tag", "Ink", [10, 10], "#F0A500", undefined, { ink: "#1F1D2B", fs: 9 }),
    ).toBeNull();
    expect(both(p, "label", "Workshop", [300, 40])).toBeNull();
    expect(both(p, "label", "", [0, 0])).toBeNull();
  });

  it("WEB_1b_world_gate_clouds_landing_lift_presence_comment_tree", () => {
    const p = pair();
    for (const st of ["open", "waiting", "closed", undefined])
      expect(both(p, "gate", 40, 60, st), `gate ${st}`).toBeNull();
    expect(both(p, "clouds", 0, 0, 110, 70, 5)).toBeNull();
    expect(both(p, "clouds", -40, 12, 300, 200)).toBeNull();
    expect(both(p, "clouds", 10, 10, 20, 20, 99)).toBeNull();
    expect(both(p, "landing", 80, 100, 240, 330)).toBeNull();
    expect(both(p, "landing", 80, 300, 240, 0)).toBeNull();
    for (const o of [
      { state: "planned" },
      { state: "idle", t: 0 },
      { state: "active", t: 0.5, parcel: true },
      { state: "idle", t: 1 },
      { state: "idle" },
    ]) {
      expect(both(p, "liftEl", 80, 240, 0, 330, o), `lift ${JSON.stringify(o)}`).toBeNull();
    }
    expect(both(p, "presence", [10, 20], "AM")).toBeNull();
    expect(both(p, "presence", [10, 20], "JP", "#D9588C")).toBeNull();
    expect(both(p, "comment", [10, 20], 3)).toBeNull();
    expect(both(p, "comment", [10, 20], 12)).toBeNull();
    expect(both(p, "comment", [10, 20], "99+")).toBeNull();
    for (const kind of ["round", "pine", undefined]) {
      expect(both(p, "tree", 100, 50, 7.5, kind), `tree ${kind}`).toBeNull();
      expect(both(p, "tree", -20, 5, 6, kind)).toBeNull();
    }
  });

  it("WEB_1b_world_agent_every_role_expression_rank_direct_call", SLOW, () => {
    const p = pair();
    for (const role of roleKeys) {
      for (const expr of EXPRESSIONS) {
        for (const rank of RANKS) {
          expect(
            both(
              p,
              "agent",
              { role, expr, rank, facing: rank === "lead" ? "R" : "L" },
              100.5,
              60.25,
            ),
            `${role}/${expr}/${rank}`,
          ).toBeNull();
        }
      }
    }
    expect(
      both(p, "agent", { role: "builder", back: true, expr: "walking" }, 10, 10, { scale: 1.15 }),
    ).toBeNull();
    expect(
      both(
        p,
        "agent",
        { role: "tester", ring: true, pack: true, parcel: true, expr: "talking" },
        10,
        10,
        { scale: 2 },
      ),
    ).toBeNull();
    expect(both(p, "agent", { role: "research" }, 0, 0)).toBeNull();
  });

  it("WEB_1b_world_building_direct_call_states_tints_and_flags", SLOW, () => {
    const p = pair();
    const kit = protoWorld().KIT as Record<string, unknown>;
    const specs = [
      ...Object.values(kit),
      { n: "Depot", fp: [2, 1], fl: 2, roof: "dome", fa: "band", i: "laptop" },
      { n: "Dock", fp: [3, 2], fl: 3, roof: "gable", fa: "arches", i: "parcel", dock: true },
      { n: "Yard", fp: [2, 2], fl: 1, roof: "flat", fa: "windows", i: "flask", yard: true },
    ];
    for (const spec of specs) {
      for (const state of BUILDING_STATES) {
        expect(
          both(p, "building", spec, state, 96, 48, { tint: "#2B98B5" }),
          `${(spec as { n: string }).n}/${state}`,
        ).toBeNull();
      }
    }
    expect(both(p, "building", specs[0], "active", 0, 0)).toBeNull();
  });

  it("WEB_1b_world_specOf_kit_and_generated", () => {
    const p = pair();
    expect(both(p, "specOf", { kit: "townhall" }, 1)).toBeNull();
    expect(both(p, "specOf", { kit: "library", name: "Reading Room", fl: 3 }, 4)).toBeNull();
    for (const name of ["Laptop Depot", "Mail Room", "", "Ünïcode name", "A".repeat(40)]) {
      for (const seed of [0, 1, 2, 17, 4001]) {
        expect(both(p, "specOf", { gen: { name } }, seed), `${name}/${seed}`).toBeNull();
        expect(
          both(
            p,
            "specOf",
            { gen: { name, fp: [2, 2], fl: 2, roof: "dome", fa: "arches", i: "cap" } },
            seed,
          ),
        ).toBeNull();
      }
    }
  });
});

describe("WEB_1b_world_layout: layout, standOf, route, along", () => {
  const plans = [
    ["k1", () => plan("k1", { depot: true, mail: true })],
    ["hires", () => plan("hires")],
    ["audit", () => plan("audit")],
    ["fresh", () => plan("fresh")],
    ["rich", richPlan],
  ] as const;

  it.each(plans)("WEB_1b_world_layout_%s_for_several_seeds", (_n, make) => {
    for (const seed of [0, 1, 2, 9, 123456]) {
      expect(both(pair(), "layout", make(), seed), `seed ${seed}`).toBeNull();
    }
  });

  it.each(plans)("WEB_1b_world_route_along_standOf_%s_every_pair", SLOW, (_n, make) => {
    const p = pair();
    const lp = call(p.port, "layout", make(), 1) as { bmap: Record<string, unknown> };
    const lr = call(p.proto, "layout", make(), 1) as { bmap: Record<string, unknown> };
    const ids = Object.keys(lr.bmap);
    expect(Object.keys(lp.bmap)).toEqual(ids);
    expect(ids.length).toBeGreaterThanOrEqual(2);
    for (const a of ids) {
      expect(
        sameAsPrototype(call(p.port, "standOf", lp.bmap[a]), call(p.proto, "standOf", lr.bmap[a])),
        `standOf ${a}`,
      ).toBeNull();
      for (const b of [...ids, "no-such-building"]) {
        const rp = call(p.port, "route", lp, a, b);
        const rr = call(p.proto, "route", lr, a, b);
        expect(sameAsPrototype(rp, rr), `route ${a}->${b}`).toBeNull();
        if (Array.isArray(rr)) {
          for (const t of [0, 0.1, 0.25, 0.5, 0.75, 0.999, 1, 1.5]) {
            expect(
              sameAsPrototype(call(p.port, "along", rp, t), call(p.proto, "along", rr, t)),
              `along ${a}->${b} @${t}`,
            ).toBeNull();
          }
        } else {
          expect(rr).toBeNull();
        }
      }
    }
    expect(call(p.port, "route", lp, "no-such-building", ids[0])).toBeNull();
  });

  it("WEB_1b_world_along_degenerate_polylines", () => {
    const p = pair();
    const cases: unknown[][] = [
      [[[0, 0]]],
      [
        [
          [0, 0],
          [0, 0],
        ],
      ],
      [
        [
          [0, 0],
          [10, 0],
          [10, 10],
          [10, 10],
          [30, 10],
        ],
      ],
      [[]],
    ];
    for (const [pts] of cases) {
      for (const t of [0, 0.3, 1, 2, -1]) {
        expect(
          sameAsPrototype(call(p.port, "along", pts, t), call(p.proto, "along", pts, t)),
          `${JSON.stringify(pts)} @${t}`,
        ).toBeNull();
      }
    }
  });
});

describe("WEB_1b_world_motion: WEB-1b adds no animation (BQ-WEB-3, ADR-0003a 5)", () => {
  it("WEB_1b_world_motion_world_with_anim_on_equals_the_prototype_with_anim_off", SLOW, () => {
    for (const make of [
      () => plan("k1", { depot: true, mail: false }),
      () => plan("hires"),
      richPlan,
    ]) {
      for (const extra of [{}, { seed: 4, stage: 3 }, { labels: false }]) {
        const p = pair();
        const port = call(p.port, "world", make(), { ...extra, anim: true });
        const proto = call(p.proto, "world", make(), { ...extra, anim: false });
        expect(sameAsPrototype(port, proto)).toBeNull();
      }
    }
  });

  it("WEB_1b_world_motion_the_reference_really_animates_with_anim_on", () => {
    // Guards the test above: with anim on, the prototype's tree carries tiloDash / tiloBob.
    const withAnim = JSON.stringify(canon(call(protoWorld(), "world", richPlan(), { anim: true })));
    expect(withAnim).toMatch(/tiloDash/);
    expect(withAnim).toMatch(/tiloBob/);
  });

  it("WEB_1b_world_motion_no_output_carries_an_animation_name_or_keyframe_reference", SLOW, () => {
    const p = pair();
    const outs = [
      call(p.port, "world", richPlan(), { anim: true }),
      call(p.port, "world", plan("k1"), {}),
      call(p.port, "metro", metroLevels(), { anim: true }),
      call(p.port, "pin", "active", [10, 10], { anim: "tiloBob 1.6s ease-in-out infinite" }),
      call(p.port, "agent", { role: "builder", expr: "walking" }, 5, 5, {
        anim: "tiloBob .45s ease-in-out infinite",
      }),
    ];
    for (const o of outs) expect(motionLeaks(o)).toEqual([]);
  });

  it("WEB_1b_world_motion_pin_and_agent_ignore_the_anim_style_string", () => {
    const p = pair();
    expect(
      sameAsPrototype(
        call(p.port, "pin", "active", [10, 10], {
          icon: "doc",
          tint: "#2B98B5",
          anim: "tiloBob 1.6s ease-in-out infinite",
        }),
        call(p.proto, "pin", "active", [10, 10], { icon: "doc", tint: "#2B98B5" }),
      ),
    ).toBeNull();
    expect(
      sameAsPrototype(
        call(p.port, "agent", { role: "tester", expr: "walking" }, 5, 5, {
          scale: 1.3,
          anim: "tiloBob .45s ease-in-out infinite",
        }),
        call(p.proto, "agent", { role: "tester", expr: "walking" }, 5, 5, { scale: 1.3 }),
      ),
    ).toBeNull();
  });

  it("WEB_1b_world_motion_metro_with_anim_on_equals_the_prototype_with_anim_off", SLOW, () => {
    const p = pair();
    expect(
      sameAsPrototype(
        call(p.port, "metro", metroLevels(), { seed: 2, anim: true }),
        call(p.proto, "metro", metroLevels(), { seed: 2, anim: false }),
      ),
    ).toBeNull();
  });
});

describe("WEB_1b_world_state: the label scale `ls` belongs to one engine instance", () => {
  it("WEB_1b_world_state_world_sets_the_label_scale_that_label_then_uses", () => {
    const p = pair();
    const steps: [string, unknown[]][] = [
      ["label", ["Workshop", [10, 10]]],
      ["world", [plan("fresh"), { ls: 1.6, stage: 2, anim: false }]],
      ["label", ["Workshop", [10, 10]]],
      ["world", [plan("fresh"), { stage: 2, anim: false }]], // no ls: back to 1
      ["label", ["Workshop", [10, 10]]],
    ];
    const seen: string[] = [];
    for (const [name, args] of steps) {
      const a = call(p.port, name, ...args);
      const b = call(p.proto, name, ...args);
      expect(sameAsPrototype(a, b), `${name} ${JSON.stringify(args).slice(0, 40)}`).toBeNull();
      if (name === "label") seen.push(JSON.stringify(canon(a)));
    }
    // Non-vacuous: the scaled label really differs from the unscaled ones.
    expect(seen[1]).not.toBe(seen[0]);
    expect(seen[2]).toBe(seen[0]);
  });

  it("WEB_1b_world_state_two_instances_do_not_share_the_scale", () => {
    const a = createWorld(serialiseH) as unknown as Engine;
    const b = createWorld(serialiseH) as unknown as Engine;
    call(a, "world", plan("fresh"), { ls: 2, anim: false });
    const fresh = protoWorld();
    expect(
      sameAsPrototype(call(b, "label", "Library", [5, 5]), call(fresh, "label", "Library", [5, 5])),
    ).toBeNull();
    expect(
      sameAsPrototype(call(a, "label", "Library", [5, 5]), call(b, "label", "Library", [5, 5])),
    ).not.toBeNull();
  });
});

describe("WEB_1b_world_determinism: no clock, no Math.random, same inputs give the same tree", () => {
  it("WEB_1b_world_determinism_calling_twice_and_on_two_instances_gives_equal_trees", SLOW, () => {
    const a = createWorld(serialiseH) as unknown as Engine;
    const b = createWorld(serialiseH) as unknown as Engine;
    const o = { seed: 11, anim: false };
    const first = call(a, "world", richPlan(), o);
    expect(sameAsPrototype(call(a, "world", richPlan(), o), first)).toBeNull();
    expect(sameAsPrototype(call(b, "world", richPlan(), o), first)).toBeNull();
    expect(
      sameAsPrototype(call(b, "world", richPlan(), { ...o, seed: 12 }), first),
      "a different seed must differ",
    ).not.toBeNull();
  });

  it("WEB_1b_world_determinism_never_reads_the_clock_or_Math_random", SLOW, () => {
    const plans = [richPlan(), plan("k1"), plan("audit")];
    const levels = metroLevels();
    vi.spyOn(Math, "random").mockImplementation(() => {
      throw new Error("Math.random was called");
    });
    vi.spyOn(Date, "now").mockImplementation(() => {
      throw new Error("Date.now was called");
    });
    const w = createWorld(serialiseH) as unknown as Engine;
    for (const pl of plans) call(w, "world", pl, { seed: 3 });
    call(w, "metro", levels, { seed: 2 });
    call(w, "soloAgent", { role: "builder", expr: "focused" });
    call(w, "soloBuilding", "library", "active");
    call(w, "clouds", 0, 0, 100, 100);
    call(w, "layout", plans[0], 5);
  });

  it("WEB_1b_world_determinism_property_world_of_the_fresh_plan_matches_for_any_seed", SLOW, () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 2 ** 31 }),
        fc.integer({ min: 1, max: 4 }),
        (seed, stage) => {
          const p = pair();
          return both(p, "world", plan("fresh"), { seed, stage, anim: false }) === null;
        },
      ),
      { numRuns: 25 },
    );
  });

  it("WEB_1b_world_determinism_property_clouds_and_specOf_match_for_any_seed", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 2 ** 31 }),
        fc.string({ maxLength: 24 }),
        fc.integer({ min: 20, max: 400 }),
        (seed, name, w) => {
          const p = pair();
          return (
            both(p, "clouds", 0, 0, w, w / 2, seed) === null &&
            both(p, "specOf", { gen: { name } }, seed) === null
          );
        },
      ),
      { numRuns: 60 },
    );
  });
});

describe("WEB_1b_world_property: projection and colour arithmetic match exactly for any input", () => {
  const num = fc.double({ min: -5000, max: 5000, noNaN: true });
  const z = fc.option(num, { nil: undefined });

  it("WEB_1b_world_property_P_mL_mR_mT_equal_the_prototype_to_the_last_bit", () => {
    const p = pair();
    fc.assert(
      fc.property(num, num, z, (x, y, zz) => {
        const a = JSON.stringify(canon(call(p.port, "P", x, y, zz)));
        const b = JSON.stringify(canon(call(p.proto, "P", x, y, zz)));
        return (
          a === b &&
          ["mL", "mR", "mT"].every((m) => call(p.port, m, x, y, zz) === call(p.proto, m, x, y, zz))
        );
      }),
      { numRuns: 300 },
    );
  });

  const channel = fc.integer({ min: 0, max: 255 });
  const hex = fc
    .tuple(channel, channel, channel)
    .map(([r, g, b]) => `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`);
  const amount = fc.option(fc.double({ min: 0, max: 1, noNaN: true }), { nil: undefined });

  it("WEB_1b_world_property_dk_and_lt_equal_the_prototype_and_stay_valid_hex_in_order", () => {
    const p = pair();
    fc.assert(
      fc.property(hex, amount, (c, t) => {
        const d = call(p.port, "dk", c, t) as string;
        const l = call(p.port, "lt", c, t) as string;
        const chan = (s: string, i: number) => Number.parseInt(s.slice(1 + 2 * i, 3 + 2 * i), 16);
        const ok = /^#[0-9a-f]{6}$/.test(d) && /^#[0-9a-f]{6}$/.test(l);
        const ordered = [0, 1, 2].every(
          (i) => chan(d, i) <= chan(c, i) && chan(l, i) >= chan(c, i),
        );
        return ok && ordered && d === call(p.proto, "dk", c, t) && l === call(p.proto, "lt", c, t);
      }),
      { numRuns: 300 },
    );
  });

  it("WEB_1b_world_property_along_stays_on_the_polyline_bounding_box_and_matches", () => {
    const p = pair();
    const point = fc.tuple(
      fc.integer({ min: -500, max: 500 }),
      fc.integer({ min: -500, max: 500 }),
    );
    fc.assert(
      fc.property(
        fc.array(point, { minLength: 2, maxLength: 8 }),
        fc.double({ min: 0, max: 1, noNaN: true }),
        (pts, t) => {
          const a = call(p.port, "along", pts, t) as { p: [number, number]; dir: string };
          const b = call(p.proto, "along", pts, t);
          const xs = pts.map((q) => q[0]);
          const ys = pts.map((q) => q[1]);
          const inside =
            a.p[0] >= Math.min(...xs) - 1e-6 &&
            a.p[0] <= Math.max(...xs) + 1e-6 &&
            a.p[1] >= Math.min(...ys) - 1e-6 &&
            a.p[1] <= Math.max(...ys) + 1e-6;
          return inside && sameAsPrototype(a, b) === null;
        },
      ),
      { numRuns: 200 },
    );
  });
});
