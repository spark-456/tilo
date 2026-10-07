// WEB-1a (docs/web-app-rebuild-plan.md sections 2, 5; BQ-WEB-5): the typed Park fixtures are the
// design prototype's data transcribed verbatim. The prototype (design_handoff_tilo_web_app/design/
// tilo-app.js) runs in a Node vm; every data member and every function result must match the TS
// fixtures (JSON-normalised: same strings, numbers and order).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { HANDOFF_DIR, loadPrototypeData, norm } from "../../../test-support/park/prototype";
import * as fx from "./fixtures";

const proto = loadPrototypeData();

// ADDITIVE members (WEB-3b): designed copy the reference shell hard-codes (`design/Tilo App.dc.html`) that the
// prototype's data does not carry. Superset check: every prototype property still deep-equals; only the paths
// listed here may be extra (`[]` = each array item), and each is pinned to the string the reference shell
// contains. A lane that needs another additive member adds one entry here and one in
// scripts/park-fixtures.mjs; drift in any other property of the prototype's data still fails.
const ADDITIVE_PATHS: Record<string, readonly string[]> = {
  decisions: ["[].toast", "[].approvedTitle", "[].facts"],
  agenda: ["rules"],
  worlds: ["[].heroTag"],
};
const ADDITIVE_VALUES: readonly (readonly [
  member: string,
  find: string,
  path: string,
  value: string,
])[] = [
  ["decisions", "depot", "toast", "Approved £3,420 for Laptop Depot"],
  ["decisions", "mail", "toast", "Supplier brief sent to 3 suppliers"],
  ["decisions", "depot", "approvedTitle", "You approved Laptop Depot"],
  ["decisions", "mail", "approvedTitle", "You sent the supplier brief"],
];

/** `value` without the additive paths of `member` (arrays are walked at `[]`). */
function withoutAdditive(member: string, value: unknown): unknown {
  const drop = (v: unknown, segs: readonly string[]): unknown => {
    const [head, ...rest] = segs;
    if (head === undefined) return v;
    if (head === "[]") return Array.isArray(v) ? v.map((x) => drop(x, rest)) : v;
    if (typeof v !== "object" || v === null) return v;
    const o = { ...(v as Record<string, unknown>) };
    if (rest.length === 0) delete o[head];
    else if (head in o) o[head] = drop(o[head], rest);
    return o;
  };
  return (ADDITIVE_PATHS[member] ?? []).reduce((v, p) => drop(v, p.split(".")), value);
}

const DEC_COMBOS = [
  { depot: false, mail: false },
  { depot: true, mail: false },
  { depot: false, mail: true },
  { depot: true, mail: true },
] as const;

const MODES = ["quick", "routine", "workspace"] as const;
// Edge cases of the prototype's name rule: empty (placeholder), short, exactly 26, 27 (sliced to 24 + ellipsis).
const QUERIES = [
  "",
  "Short task",
  "abcdefghijklmnopqrstuvwxyz",
  "abcdefghijklmnopqrstuvwxyz1",
  "A very long task description that goes well past twenty six characters",
];

describe("WEB_1a_fixtures_match_prototype: the reference side is real", () => {
  it("WEB_1a_prototype_loads_and_is_not_empty", () => {
    expect(proto.decisions).toHaveLength(2);
    expect(proto.skills).toHaveLength(8);
    expect(proto.worlds({})).toHaveLength(11);
    expect(proto.connectors).toHaveLength(12);
    expect(proto.notifications).toHaveLength(5);
    expect(Object.keys(proto.TIERS)).toEqual(["quick", "routine", "workspace"]);
  });
});

describe("WEB_1a_fixtures_match_prototype: data members", () => {
  it.each([
    "user",
    "today",
    "skills",
    "learn",
    "ledger",
    "agenda",
    "team",
    "connectors",
    "notifications",
    "TIERS",
    "LEVELS",
  ] as const)("WEB_1a_fixtures_match_prototype %s is identical to the prototype", (name) => {
    expect(
      norm(withoutAdditive(name, fx[name])),
      `fixtures.${name} differs from tilo-app.js`,
    ).toEqual(norm(proto[name]));
  });

  it("WEB_9c_fixtures_additive_fields_are_the_only_difference", () => {
    // additive.ts adds `Agenda.rules` and `Decision.facts`; the identical-to-prototype checks strip exactly
    // the ADDITIVE_PATHS and still fail on any other drift. Here: the additions exist and nothing else is extra.
    expect(fx.agenda.rules).toBeDefined();
    expect(fx.decisions.every((d) => d.facts !== undefined)).toBe(true);
    expect(Object.keys(fx.agenda).filter((k) => !(k in (proto.agenda as object)))).toEqual([
      "rules",
    ]);
  });

  it("WEB_9c_fixtures_agenda_rules_hold_the_designed_agenda_page_copy", () => {
    // The rules' display strings are pinned to the Agenda reference page (`design/Tilo App Agenda.dc.html`).
    const reference = fs.readFileSync(
      path.join(HANDOFF_DIR, "design", "Tilo App Agenda.dc.html"),
      "utf8",
    );
    const r = fx.agenda.rules;
    if (r === undefined) throw new Error("fixtures.agenda.rules is missing");
    const find = r.suggestions.find?.find;
    const focus = r.suggestions.focus;
    const copy = [
      r.month,
      r.dateLine,
      r.boardSubs?.team,
      r.suggestions.find?.label,
      find?.title,
      find?.sub,
      find?.pin.title,
      find?.pin.due,
      find?.pin.noteAfter,
      focus?.label,
      focus?.toast,
      focus?.accepted?.title,
      focus?.accepted?.note,
      focus?.accepted?.due,
      r.briefRewrites[0]?.text,
    ];
    // BQ-UX15-2: while there is no calendar connector these three strings must not claim Google Calendar did
    // something, so the honesty rules beat parity for exactly them (the design page's wording is the old claim).
    const HONEST_COPY = new Set([
      "Invites to Jin, Priya and Tom go out once Google Calendar is connected and you approve.",
      "Blocked 09:30–11:30 on Monday on your Agenda",
      "09:30–11:30, added to your Agenda",
    ]);
    for (const text of copy) {
      expect(text, "an agenda rule string is missing").toBeTruthy();
      if (HONEST_COPY.has(text as string)) continue;
      expect(reference, `the Agenda reference page has "${text}"`).toContain(text as string);
    }
    expect(
      [find?.pin.noteAfter, focus?.toast, focus?.accepted?.note].every((t) =>
        HONEST_COPY.has(t as string),
      ),
    ).toBe(true);
  });

  it("WEB_1a_fixtures_match_prototype decisions: the prototype's own data is identical, only the listed paths are extra", () => {
    expect(norm(withoutAdditive("decisions", fx.decisions))).toEqual(norm(proto.decisions));
  });

  it("WEB_1a_fixtures_match_prototype additive members: every listed path exists and holds the reference shell's string", () => {
    const reference = fs.readFileSync(path.join(HANDOFF_DIR, "design", "Tilo App.dc.html"), "utf8");
    for (const [member, k, key, want] of ADDITIVE_VALUES) {
      const item = (fx[member as "decisions"] as unknown as Record<string, string>[]).find(
        (d) => d.k === k,
      );
      expect(item?.[key], `${member}.${k}.${key}`).toBe(want);
      expect(reference, `the reference shell has "${want}"`).toContain(want);
    }
    // no extra key outside the listed ones: stripping them leaves exactly the prototype's keys (the test above)
    expect(Object.keys(ADDITIVE_PATHS)).toEqual(["decisions", "agenda", "worlds"]);
    // WEB-6: the K1 hero tag is the World reference page's own line (`heroTag` is the only extra world key, on one world)
    const world = fs.readFileSync(
      path.join(HANDOFF_DIR, "design", "Tilo App World.dc.html"),
      "utf8",
    );
    const tagged = fx.worlds({}).filter((w) => w.heroTag !== undefined);
    expect(tagged).toHaveLength(1);
    expect(world).toContain(tagged[0]?.heroTag as string);
  });

  it("WEB_1a_fixtures_match_prototype the merged final state is what is transcribed (skills, ledger, team)", () => {
    // tilo-app.js builds these in several passes (SX merge, splice, Object.assign); the fixtures hold the end state.
    expect(fx.skills.map((s) => s.id)).toEqual((proto.skills as { id: string }[]).map((s) => s.id));
    expect(Object.keys(fx.ledger)).toEqual(Object.keys(proto.ledger as object));
    expect(norm(fx.team.coverage)).toEqual(norm((proto.team as { coverage: unknown }).coverage));
  });
});

describe("WEB_1a_fixtures_match_prototype: functions", () => {
  it.each(DEC_COMBOS)("WEB_1a_fixtures_match_prototype needsLeft(%o)", (dec) => {
    expect(fx.needsLeft(dec)).toBe(proto.needsLeft(dec));
  });

  it.each(DEC_COMBOS)("WEB_1a_fixtures_match_prototype plans(%o)", (dec) => {
    expect(norm(fx.plans(dec))).toEqual(norm(proto.plans(dec)));
  });

  it.each(DEC_COMBOS)("WEB_1a_fixtures_match_prototype worlds(%o, []) ", (dec) => {
    expect(norm(withoutAdditive("worlds", fx.worlds(dec, [])))).toEqual(
      norm(proto.worlds(dec, [])),
    );
  });

  it("WEB_1a_fixtures_match_prototype makeWorld for every mode and name edge case", () => {
    for (const mode of MODES) {
      for (const q of QUERIES) {
        for (const i of [1, 2]) {
          expect(
            norm(fx.makeWorld(mode, q, i)),
            `makeWorld(${mode}, ${JSON.stringify(q)}, ${i})`,
          ).toEqual(norm(proto.makeWorld(mode, q, i)));
        }
      }
    }
  });

  it.each(DEC_COMBOS)("WEB_1a_fixtures_match_prototype worlds(%o, [added world])", (dec) => {
    for (const mode of MODES) {
      const mine = fx.worlds(dec, [fx.makeWorld(mode, "Plan the offsite", 1)]);
      const theirs = proto.worlds(dec, [proto.makeWorld(mode, "Plan the offsite", 1)]);
      expect(norm(withoutAdditive("worlds", mine)), `added ${mode} world`).toEqual(norm(theirs));
      expect(mine).toHaveLength(12);
      expect(mine[0]?.id).toBe("new1");
    }
  });

  it("WEB_1a_fixtures_match_prototype gbp over a spread of values", () => {
    for (const v of [0, 0.4, 0.38, 99.5, 100, 2412, 3420, 8000, 1234567]) {
      expect(fx.gbp(v), `gbp(${v})`).toBe(proto.gbp(v));
    }
    // Anchors, so a wrong prototype load cannot make this vacuous.
    expect(fx.gbp(0.4)).toBe("£0.40");
    expect(fx.gbp(99.5)).toBe("£99.50");
    expect(fx.gbp(100)).toBe("£100");
    expect(fx.gbp(3420)).toBe("£3,420");
    expect(fx.gbp(1234567)).toBe("£1,234,567");
  });

  it("WEB_1a_fixtures_match_prototype each call returns fresh objects (no shared mutable plan or world)", () => {
    const a = fx.worlds({ depot: false, mail: false }, []);
    const b = fx.worlds({ depot: false, mail: false }, []);
    expect(a).toEqual(b);
    expect(a).not.toBe(b);
    expect(a[0]).not.toBe(b[0]);
    expect(fx.plans({})).not.toBe(fx.plans({}));
  });
});

describe("WEB_1a_fixtures_match_prototype: the decision effects the design relies on", () => {
  it("WEB_1a_fixtures_match_prototype approving both decisions leaves nothing needing the person", () => {
    expect(fx.needsLeft({ depot: false, mail: false })).toBe(2);
    expect(fx.needsLeft({ depot: true, mail: false })).toBe(1);
    expect(fx.needsLeft({ depot: true, mail: true })).toBe(0);
    const k1 = (dec: Parameters<typeof fx.worlds>[0]) =>
      fx.worlds(dec, []).find((w) => w.id === "k1");
    expect(k1({ depot: false, mail: false })?.st).toBe("needs");
    expect(k1({ depot: true, mail: true })?.st).toBe("running");
  });
});
