// WEB-1a (docs/web-app-rebuild-plan.md sections 2, 5; BQ-WEB-5): the typed Park fixtures are the
// design prototype's data transcribed verbatim. The prototype (design_handoff_tilo_web_app/design/
// tilo-app.js) runs in a Node vm; every data member and every function result must match the TS
// fixtures (JSON-normalised: same strings, numbers and order).
import { describe, expect, it } from "vitest";
import { loadPrototypeData, norm } from "../../../test-support/park/prototype";
import * as fx from "./fixtures";

const proto = loadPrototypeData();

/** `value` without the additive fields of additive.ts (`Agenda.rules`, `Decision.facts`): the prototype's own. */
function prototypeFields(name: string, value: unknown): unknown {
  if (name === "agenda") {
    const { rules: _rules, ...own } = value as { rules?: unknown };
    return own;
  }
  if (name === "decisions")
    return (value as { facts?: unknown }[]).map(({ facts: _facts, ...own }) => own);
  return value;
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
    "decisions",
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
      norm(prototypeFields(name, fx[name])),
      `fixtures.${name} differs from tilo-app.js`,
    ).toEqual(norm(proto[name]));
  });

  it("WEB_9c_fixtures_additive_fields_are_the_only_difference", () => {
    // additive.ts adds `Agenda.rules` and `Decision.facts`; nothing else may differ from the prototype.
    expect(fx.agenda.rules).toBeDefined();
    expect(fx.decisions.every((d) => d.facts !== undefined)).toBe(true);
    expect(Object.keys(fx.agenda).filter((k) => !(k in (proto.agenda as object)))).toEqual([
      "rules",
    ]);
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
    expect(norm(fx.worlds(dec, []))).toEqual(norm(proto.worlds(dec, [])));
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
      expect(norm(mine), `added ${mode} world`).toEqual(norm(theirs));
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
