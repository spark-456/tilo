// WEB-1c (docs/web-app-rebuild-plan.md sections 2, 5, 9): the kit memoises exactly as the prototype's does
// (tilo-app.js: `ck(k, f) = (k in C) ? C[k] : (C[k] = f())`; keys 'a|'+JSON.stringify(a)+'|'+s+'|'+!!night,
// 'b|'+JSON.stringify(spec)+st+dist+ht+!!night, 'w|'+key+'|'+!!night, WEB-3b: key = plan + the decision flags that are on, no plan is special-cased).
// The prototype keeps one module-level cache; the port keeps one cache per kit instance.
//
// Engine calls are counted without touching the engines: the kit's `h` and the park's injected
// `env.createObjectURL` are wrapped. A cache hit must add no `h` call and no image blob; a miss adds both.
// The key strings are pinned by seeding the shared cache through `ck` with a sentinel and asking the
// memoised function for it. Pinned decisions are listed in the WEB-1c report.
import * as fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import {
  FakeBlob,
  type TestH,
  canon,
  fakeCreateObjectURL,
  serialiseH,
} from "../../../test-support/park/engineProto";
import { type Kit, type KitDeps, type MakeKit, nodesOf } from "../../../test-support/park/kitProto";
import { plans as fixturePlans } from "../api/fixtures";
import { createKit } from "./kit";

const SLOW = { timeout: 120_000 };

/** A kit whose engine work can be counted: `h` calls and image blobs made. */
function counted() {
  const n = { h: 0, urls: 0 };
  const h: TestH = (tag, props, ...children) => {
    n.h++;
    return serialiseH(tag, props, ...children);
  };
  const env = {
    Blob: FakeBlob,
    createObjectURL: (b: FakeBlob) => {
      n.urls++;
      return fakeCreateObjectURL(b);
    },
  };
  const plans = vi.fn(fixturePlans as unknown as KitDeps["plans"]);
  const kit = (createKit as unknown as MakeKit)(h, { plans, env });
  const snap = () => ({ ...n });
  return { kit, plans, n, snap };
}
/** The engine work done by `f`. */
function work<T>(c: ReturnType<typeof counted>, f: () => T): { out: T; h: number; urls: number } {
  const a = c.snap();
  const out = f();
  return { out, h: c.n.h - a.h, urls: c.n.urls - a.urls };
}

const A = { role: "builder", expr: "focused" };

describe("WEB_1c_memo_agent: agent(a, size, night) is cached by 'a|' + JSON + size + night", () => {
  it("WEB_1c_memo_agent_equal_arguments_return_the_identical_object_and_call_the_engine_once", () => {
    const c = counted();
    const first = work(c, () => c.kit.agent({ ...A }, 90, false));
    expect(first.h, "the first call draws").toBeGreaterThan(0);
    expect(first.urls, "the first call makes an image").toBeGreaterThan(0);
    const again = work(c, () => c.kit.agent({ ...A }, 90, false)); // a new, equal object
    expect(again.out).toBe(first.out);
    expect(again.h).toBe(0);
    expect(again.urls).toBe(0);
  });

  it("WEB_1c_memo_agent_a_missing_night_flag_is_day_and_a_missing_size_is_its_own_entry", () => {
    const c = counted();
    const day = c.kit.agent({ ...A }, 90, false);
    expect(c.kit.agent({ ...A }, 90)).toBe(day);
    expect(c.kit.agent({ ...A }, 90, undefined)).toBe(day);
    const noSize = c.kit.agent({ ...A });
    expect(noSize).not.toBe(day);
    expect(c.kit.agent({ ...A }, undefined, false)).toBe(noSize);
  });

  it("WEB_1c_memo_agent_a_different_night_flag_size_or_look_is_a_distinct_entry_and_draws", () => {
    const c = counted();
    const base = c.kit.agent({ ...A }, 90, false);
    for (const f of [
      () => c.kit.agent({ ...A }, 90, true),
      () => c.kit.agent({ ...A }, 36, false),
      () => c.kit.agent({ ...A, expr: "needs" }, 90, false),
      () => c.kit.agent({ ...A, rank: "lead" }, 90, false),
      () => c.kit.agent({ role: "tester", expr: "focused" }, 90, false),
      () => c.kit.agent({ expr: "focused", role: "builder" }, 90, false), // key order is part of the key
    ]) {
      const r = work(c, f);
      expect(r.out).not.toBe(base);
      expect(r.h, "a miss draws").toBeGreaterThan(0);
    }
  });

  it("WEB_1c_memo_agent_night_and_day_pictures_differ_so_the_flag_is_not_dropped", () => {
    const c = counted();
    const day = JSON.stringify(canon(c.kit.agent({ ...A }, 90, false)));
    const night = JSON.stringify(canon(c.kit.agent({ ...A }, 90, true)));
    expect(night).not.toBe(day);
  });
});

describe("WEB_1c_memo_building: building(spec, state, dist, ht, night) is cached by 'b|' + JSON(spec) + state + dist + ht + night", () => {
  it("WEB_1c_memo_building_equal_arguments_return_the_identical_object_and_call_the_engine_once", () => {
    const c = counted();
    const first = work(c, () => c.kit.building("library", "active", "research", 150, false));
    expect(first.h).toBeGreaterThan(0);
    expect(first.urls).toBeGreaterThan(0);
    const again = work(c, () => c.kit.building("library", "active", "research", 150, false));
    expect(again.out).toBe(first.out);
    expect(again.h).toBe(0);
    expect(again.urls).toBe(0);
  });

  it("WEB_1c_memo_building_spec_objects_are_keyed_by_their_content", () => {
    const c = counted();
    const a = c.kit.building(
      { fp: [2, 1], fl: 1, roof: "flat", fa: "windows", i: "mail" },
      "idle",
      "mail",
      120,
      false,
    );
    const b = work(c, () =>
      c.kit.building(
        { fp: [2, 1], fl: 1, roof: "flat", fa: "windows", i: "mail" },
        "idle",
        "mail",
        120,
        false,
      ),
    );
    expect(b.out).toBe(a);
    expect(b.h).toBe(0);
    expect(
      c.kit.building(
        { fp: [2, 1], fl: 1, roof: "flat", fa: "windows", i: "laptop" },
        "idle",
        "mail",
        120,
        false,
      ),
    ).not.toBe(a);
  });

  it("WEB_1c_memo_building_a_different_night_flag_state_district_height_or_spec_is_a_distinct_entry", () => {
    const c = counted();
    const base = c.kit.building("library", "active", "research", 150, false);
    for (const f of [
      () => c.kit.building("library", "active", "research", 150, true),
      () => c.kit.building("library", "idle", "research", 150, false),
      () => c.kit.building("library", "active", "delivery", 150, false),
      () => c.kit.building("library", "active", "research", 90, false),
      () => c.kit.building("library", "active", undefined, 150, false),
      () => c.kit.building("dock", "active", "research", 150, false),
    ]) {
      const r = work(c, f);
      expect(r.out).not.toBe(base);
      expect(r.h, "a miss draws").toBeGreaterThan(0);
    }
    expect(c.kit.building("library", "active", "research", 150)).toBe(base);
    expect(c.kit.building("library", "active", "research", 150, undefined)).toBe(base);
  });
});

describe("WEB_1c_memo_world: world(planId, dec, night) is cached by plan, the decision flags that are on, and night", () => {
  it("WEB_1c_memo_world_equal_arguments_return_the_identical_object_and_build_the_plan_and_picture_once", () => {
    const c = counted();
    expect(c.plans, "createKit does not read the plans").not.toHaveBeenCalled();
    const first = work(c, () => c.kit.world("k1", { depot: true, mail: false }, false));
    expect(first.h).toBeGreaterThan(0);
    expect(first.urls).toBeGreaterThan(0);
    expect(c.plans).toHaveBeenCalledTimes(1);
    expect(c.plans).toHaveBeenLastCalledWith({ depot: true, mail: false });
    const again = work(c, () => c.kit.world("k1", { depot: true, mail: false }, false));
    expect(again.out).toBe(first.out);
    expect(again.h).toBe(0);
    expect(again.urls).toBe(0);
    expect(c.plans, "a hit does not ask for the plans again").toHaveBeenCalledTimes(1);
  });

  it("WEB_1c_memo_world_the_decision_flags_that_are_on_make_the_key_and_off_ones_do_not", () => {
    const c = counted();
    const dep = c.kit.world("k1", { depot: true }, false);
    expect(c.kit.world("k1", { depot: true, mail: false }, false)).toBe(dep);
    expect(c.kit.world("k1", { depot: true, mail: false, other: true } as never, false)).not.toBe(
      dep,
    );
    const none = c.kit.world("k1", undefined, false);
    expect(none).not.toBe(dep);
    expect(c.kit.world("k1", {}, false)).toBe(none);
    expect(c.kit.world("k1", { depot: false, mail: false }, false)).toBe(none);
    const all = [
      c.kit.world("k1", { depot: false, mail: false }, false),
      c.kit.world("k1", { depot: true, mail: false }, false),
      c.kit.world("k1", { depot: false, mail: true }, false),
      c.kit.world("k1", { depot: true, mail: true }, false),
    ];
    expect(new Set(all).size, "four decision combinations, four entries").toBe(4);
  });

  it("WEB_1c_memo_world_every_plan_is_keyed_by_its_decision_flags_the_same_way", () => {
    const c = counted();
    const hires = c.kit.world("hires", { depot: true }, false);
    const again = work(c, () => c.kit.world("hires", { depot: true, mail: false }, false));
    expect(again.out).toBe(hires);
    expect(again.h).toBe(0);
    expect(c.kit.world("hires", { mail: true }, false)).not.toBe(hires);
    expect(c.kit.world("hires", undefined, false)).not.toBe(hires);
    expect(c.kit.world("audit", { depot: true }, false)).not.toBe(hires);
    expect(c.kit.world("fresh", {}, false)).not.toBe(c.kit.world("audit", {}, false));
  });

  it("WEB_1c_memo_world_a_different_night_flag_is_a_distinct_entry_and_a_missing_one_is_day", () => {
    const c = counted();
    const day = c.kit.world("fresh", {}, false);
    expect(c.kit.world("fresh", {})).toBe(day);
    expect(c.kit.world("fresh")).toBe(day);
    const night = work(c, () => c.kit.world("fresh", {}, true));
    expect(night.out).not.toBe(day);
    expect(night.h).toBeGreaterThan(0);
    expect(JSON.stringify(canon(night.out))).not.toBe(JSON.stringify(canon(day)));
  });
});

describe("WEB_1c_memo_keys: the cache keys are the prototype's strings, the world key in the generic form (seeded through ck)", () => {
  const SENT = { sentinel: true };

  it.each([
    ['a|{"role":"builder"}|90|false', (k: Kit) => k.agent({ role: "builder" }, 90, false)],
    ['a|{"role":"builder"}|90|false', (k: Kit) => k.agent({ role: "builder" }, 90)],
    ['a|{"role":"builder"}|90|true', (k: Kit) => k.agent({ role: "builder" }, 90, true)],
    ['a|{"role":"builder"}|undefined|false', (k: Kit) => k.agent({ role: "builder" })],
    [
      'a|{"role":"tester","expr":"needs"}|36|true',
      (k: Kit) => k.agent({ role: "tester", expr: "needs" }, 36, true),
    ],
    [
      'b|"library"activeresearch150false',
      (k: Kit) => k.building("library", "active", "research", 150, false),
    ],
    [
      'b|"library"activeresearch150true',
      (k: Kit) => k.building("library", "active", "research", 150, true),
    ],
    ['b|"library"activeundefinedundefinedfalse', (k: Kit) => k.building("library", "active")],
    [
      'b|{"fp":[2,1],"i":"mail"}idlemail120true',
      (k: Kit) => k.building({ fp: [2, 1], i: "mail" }, "idle", "mail", 120, true),
    ],
    ["w|k1||false", (k: Kit) => k.world("k1")],
    ["w|k1||false", (k: Kit) => k.world("k1", {}, false)],
    ["w|k1|depot|false", (k: Kit) => k.world("k1", { depot: true }, false)],
    ["w|k1|mail|false", (k: Kit) => k.world("k1", { mail: true }, false)],
    ["w|k1|depot+mail|true", (k: Kit) => k.world("k1", { depot: true, mail: true }, true)],
    ["w|hires|depot|false", (k: Kit) => k.world("hires", { depot: true }, false)],
    ["w|fresh||true", (k: Kit) => k.world("fresh", undefined, true)],
  ] as const)("WEB_1c_memo_keys_case_%# %s", (key, ask) => {
    const c = counted();
    expect(c.kit.ck(key, () => SENT)).toBe(SENT);
    const r = work(c, () => ask(c.kit));
    expect(r.out, "the memoised function reads the entry under this key").toBe(SENT);
    expect(r.h, "and does not draw").toBe(0);
    expect(c.plans, "nor ask for the plans").not.toHaveBeenCalled();
  });

  it("WEB_1c_memo_keys_the_memoised_functions_and_ck_share_one_cache", () => {
    const c = counted();
    const a = c.kit.agent({ role: "builder" }, 90, false);
    const other = { not: "the agent" };
    expect(c.kit.ck('a|{"role":"builder"}|90|false', () => other)).toBe(a);
  });
});

describe("WEB_1c_memo_ck: ck(key, f) caches by key", () => {
  it("WEB_1c_memo_ck_returns_the_cached_value_even_when_the_factory_would_return_something_else", () => {
    const { kit } = counted();
    expect(kit.ck("k", () => "first")).toBe("first");
    const f = vi.fn(() => "second");
    expect(kit.ck("k", f)).toBe("first");
    expect(f).not.toHaveBeenCalled();
    expect(kit.ck("other", () => 7)).toBe(7);
  });

  it("WEB_1c_memo_ck_calls_the_factory_once_and_caches_falsy_values_too", () => {
    const { kit } = counted();
    for (const v of [0, "", false, null, undefined, Number.NaN]) {
      const key = `falsy-${String(v)}`;
      const f = vi.fn(() => v);
      expect(Object.is(kit.ck(key, f), v), key).toBe(true);
      expect(Object.is(kit.ck(key, f), v), `${key} again`).toBe(true);
      expect(f, key).toHaveBeenCalledTimes(1);
    }
  });

  it("WEB_1c_memo_ck_returns_the_same_object_each_time", () => {
    const { kit } = counted();
    const o = kit.ck("obj", () => ({ a: [1, 2] }));
    expect(kit.ck("obj", () => ({ a: [3] }))).toBe(o);
  });
});

describe("WEB_1c_memo_instances: the cache is per kit instance, not module-global", () => {
  it("WEB_1c_memo_instances_two_kits_do_not_share_entries", () => {
    const a = counted();
    const b = counted();
    const x = a.kit.agent({ ...A }, 90, false);
    const before = b.snap();
    const y = b.kit.agent({ ...A }, 90, false);
    expect(y, "b draws its own").not.toBe(x);
    expect(b.n.h - before.h, "and does the engine work itself").toBeGreaterThan(0);
    expect(JSON.stringify(canon(y))).toBe(JSON.stringify(canon(x)));
    expect(a.kit.agent({ ...A }, 90, false), "a still has its own entry").toBe(x);
    a.kit.ck("only-a", () => 1);
    expect(b.kit.ck("only-a", () => 2)).toBe(2);
  });

  it("WEB_1c_memo_instances_a_kit_made_later_does_not_reset_an_earlier_one", () => {
    const a = counted();
    const x = a.kit.world("fresh", {}, false);
    counted().kit.world("fresh", {}, false);
    expect(a.kit.world("fresh", {}, false)).toBe(x);
  });

  it("WEB_1c_memo_instances_each_kit_draws_with_its_own_h", () => {
    const seenA: string[] = [];
    const seenB: string[] = [];
    const mk = (seen: string[]) =>
      (createKit as unknown as MakeKit)(
        (tag, props, ...c) => {
          seen.push(tag);
          return serialiseH(tag, props, ...c);
        },
        {
          plans: fixturePlans as unknown as KitDeps["plans"],
          env: { Blob: FakeBlob, createObjectURL: fakeCreateObjectURL },
        },
      );
    const a = mk(seenA);
    const b = mk(seenB);
    a.icon("home", 16);
    expect(seenA).toContain("svg");
    expect(seenB).toEqual([]);
    b.agent({ role: "builder" }, 90, false);
    expect(seenB).toContain("img");
    expect(seenA).not.toContain("img");
  });
});

describe("WEB_1c_memo_icon: icon is not cached", () => {
  it("WEB_1c_memo_icon_two_calls_give_equal_trees_that_are_not_the_same_object", () => {
    const c = counted();
    const a = c.kit.icon("home", 16);
    const again = work(c, () => c.kit.icon("home", 16));
    expect(again.out).not.toBe(a);
    expect(again.h, "it builds again").toBeGreaterThan(0);
    expect(JSON.stringify(canon(again.out))).toBe(JSON.stringify(canon(a)));
  });
});

describe("WEB_1c_memo_art: art(w, ht, night) is the first building of w.single or w.row", () => {
  it("WEB_1c_memo_art_returns_null_when_w_has_neither_single_nor_row", () => {
    const c = counted();
    for (const w of [
      {},
      { single: null, row: null },
      { single: undefined, row: undefined },
      { row: [] },
    ]) {
      const r = work(c, () => c.kit.art(w, 150, false));
      expect(r.out, JSON.stringify(w)).toBeNull();
      expect(r.h, "nothing is drawn").toBe(0);
    }
  });

  it("WEB_1c_memo_art_is_the_memoised_building_of_single", () => {
    const c = counted();
    const w = { single: ["library", "complete", "research"] };
    const art = c.kit.art(w, 150, false);
    expect(art).not.toBeNull();
    const again = work(c, () => c.kit.building("library", "complete", "research", 150, false));
    expect(again.out).toBe(art);
    expect(again.h).toBe(0);
    expect(c.kit.art(w, 150, false)).toBe(art);
    expect(c.kit.art(w, 150, true)).not.toBe(art);
    expect(c.kit.art(w, 90, false)).not.toBe(art);
  });

  it("WEB_1c_memo_art_uses_the_first_slot_of_row_and_single_wins_over_row", () => {
    const c = counted();
    const row = [
      ["dock", "active", "delivery"],
      ["vault", "idle", "analysis"],
    ];
    const first = c.kit.building("dock", "active", "delivery", 100, false);
    expect(c.kit.art({ row }, 100, false)).toBe(first);
    const single = ["desk", "idle", "mail"];
    expect(c.kit.art({ single, row }, 100, false)).toBe(
      c.kit.building("desk", "idle", "mail", 100, false),
    );
    expect(c.kit.art({ single, row }, 100, false)).not.toBe(first);
  });
});

describe("WEB_1c_memo_strip: strip(w, ht, night) is a row of keyed, overlapping, memoised buildings", () => {
  const row = [
    ["connector", "active", "mail"],
    ["dock", "active", "delivery"],
    [{ fp: [2, 1], fl: 1, roof: "flat", fa: "windows", i: "mail" }, "idle", "mail"],
  ];
  type Slot = {
    tag: string;
    props: { key: number; style: { marginLeft: number } };
    children: unknown[];
  };

  it("WEB_1c_memo_strip_is_null_without_a_row", () => {
    const c = counted();
    for (const w of [{}, { row: null }, { row: undefined }, { single: ["desk", "idle", "mail"] }]) {
      const r = work(c, () => c.kit.strip(w, 150, false));
      expect(r.out, JSON.stringify(w)).toBeNull();
      expect(r.h).toBe(0);
    }
  });

  it("WEB_1c_memo_strip_marginLeft_is_minus_14_after_the_first_slot_and_0_for_the_first", () => {
    const { kit } = counted();
    const slots = kit.strip({ row }, 150, false) as Slot[];
    expect(slots).toHaveLength(3);
    expect(slots.map((s) => s.props.style.marginLeft)).toEqual([0, -14, -14]);
    expect(Object.is(slots[0]?.props.style.marginLeft, 0), "0, not -0").toBe(true);
  });

  it("WEB_1c_memo_strip_key_props_equal_the_index_and_each_slot_is_a_div", () => {
    const { kit } = counted();
    const slots = kit.strip({ row }, 150, false) as Slot[];
    expect(slots.map((s) => s.props.key)).toEqual([0, 1, 2]);
    for (const s of slots) {
      expect(s.tag).toBe("div");
      expect(s.children).toHaveLength(1);
    }
  });

  it("WEB_1c_memo_strip_each_slot_holds_the_memoised_building_for_its_slot", () => {
    const c = counted();
    const slots = c.kit.strip({ row }, 150, true) as Slot[];
    const expected = [
      c.kit.building("connector", "active", "mail", 150, true),
      c.kit.building("dock", "active", "delivery", 150, true),
      c.kit.building(row[2]?.[0], "idle", "mail", 150, true),
    ];
    slots.forEach((s, i) => expect(s.children[0], `slot ${i}`).toBe(expected[i]));
    const again = work(c, () => c.kit.strip({ row }, 150, true) as Slot[]);
    expect(again.h, "the second strip builds only the divs").toBeLessThanOrEqual(3);
    expect(again.urls, "and no image").toBe(0);
    again.out.forEach((s, i) => expect(s.children[0], `again ${i}`).toBe(expected[i]));
    expect(again.out, "the strip itself is rebuilt, not cached").not.toBe(slots);
  });

  it("WEB_1c_memo_strip_an_empty_row_is_an_empty_list_and_a_one_slot_row_has_margin_0", () => {
    const { kit } = counted();
    expect(kit.strip({ row: [] }, 150, false)).toEqual([]);
    const one = kit.strip({ row: [row[0]] }, 150, false) as Slot[];
    expect(one.map((s) => s.props.style.marginLeft)).toEqual([0]);
  });

  it("WEB_1c_memo_strip_reads_the_buildings_through_the_building_cache_key", () => {
    const c = counted();
    expect(c.kit.ck('b|"desk"idlemail100false', () => "SENT")).toBe("SENT");
    const slots = c.kit.strip({ row: [["desk", "idle", "mail"]] }, 100, false) as Slot[];
    expect(nodesOf(slots).length).toBe(1);
    expect(slots[0]?.children).toEqual(["SENT"]);
  });
});

describe("WEB_1c_memo_property: for any call sequence, replaying it costs no engine work", () => {
  const call = fc.oneof(
    fc.tuple(
      fc.constant("agent" as const),
      fc.constantFrom("builder", "tester"),
      fc.constantFrom(undefined, 36, 90),
      fc.constantFrom(undefined, false, true),
    ),
    fc.tuple(
      fc.constant("building" as const),
      fc.constantFrom("library", "dock"),
      fc.constantFrom("active", "idle"),
      fc.constantFrom(undefined, true),
    ),
    fc.tuple(
      fc.constant("world" as const),
      fc.constantFrom("fresh", "hires"),
      fc.constantFrom(undefined, false, true),
      fc.constant(undefined),
    ),
  );
  type Call =
    | ["agent", string, number | undefined, boolean | undefined]
    | ["building", string, string, boolean | undefined]
    | ["world", string, boolean | undefined, undefined];
  const run = (k: Kit, c: Call): unknown => {
    if (c[0] === "agent") return k.agent({ role: c[1] }, c[2], c[3]);
    if (c[0] === "building") return k.building(c[1], c[2], "research", 100, c[3]);
    return k.world(c[1], {}, c[2]);
  };
  const keyOf = (c: Call): string => {
    if (c[0] === "agent") return `a|${JSON.stringify({ role: c[1] })}|${c[2]}|${!!c[3]}`;
    if (c[0] === "building") return `b|${JSON.stringify(c[1])}${c[2]}research100${!!c[3]}`;
    return `w|${c[1]}|${!!c[2]}`;
  };

  it("WEB_1c_memo_property_a_replay_returns_the_same_objects_and_does_no_engine_work", SLOW, () => {
    fc.assert(
      fc.property(fc.array(call, { minLength: 1, maxLength: 8 }), (calls) => {
        const c = counted();
        const first = calls.map((x) => run(c.kit, x));
        const before = c.snap();
        const second = calls.map((x) => run(c.kit, x));
        const distinctResults = new Set(first).size;
        const distinctKeys = new Set(calls.map(keyOf)).size;
        return (
          second.every((r, i) => r === first[i]) &&
          c.n.h === before.h &&
          c.n.urls === before.urls &&
          distinctResults === distinctKeys
        );
      }),
      { numRuns: 15 },
    );
  });
});
