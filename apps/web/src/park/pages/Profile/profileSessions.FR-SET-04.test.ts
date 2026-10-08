// FR-SET-04 (Security: "Sign out one session or every session except this one"): the pure session model.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { ProfileSession } from "../../api/types";
import { signOutOne, signOutOthers } from "./profileSessions";

const mk = (id: string, current = false): ProfileSession => ({
  id,
  device: `Device ${id}`,
  place: "Somewhere",
  lastActive: "now",
  icon: "laptop",
  ...(current ? { current } : {}),
});
const SAMPLE = [mk("a", true), mk("b"), mk("c")];

describe("FR_SET_04 signOutOne", () => {
  it("FR_SET_04_signOutOne_removes_exactly_that_session", () => {
    expect(signOutOne(SAMPLE, "b").map((s) => s.id)).toEqual(["a", "c"]);
  });
  it("FR_SET_04_signOutOne_unknown_id_changes_nothing", () => {
    expect(signOutOne(SAMPLE, "zzz")).toEqual(SAMPLE);
  });
  it("FR_SET_04_signOutOne_never_removes_the_current_session", () => {
    expect(signOutOne(SAMPLE, "a")).toEqual(SAMPLE);
  });
  it("FR_SET_04_signOutOne_does_not_mutate_its_input", () => {
    const copy = structuredClone(SAMPLE);
    signOutOne(SAMPLE, "b");
    expect(SAMPLE).toEqual(copy);
  });
});

describe("FR_SET_04 signOutOthers", () => {
  it("FR_SET_04_signOutOthers_keeps_only_the_current_session", () => {
    expect(signOutOthers(SAMPLE, "a").map((s) => s.id)).toEqual(["a"]);
  });
  it("FR_SET_04_signOutOthers_unknown_current_id_removes_nothing", () => {
    expect(signOutOthers(SAMPLE, "zzz")).toEqual(SAMPLE);
    expect(signOutOthers(SAMPLE, "")).toEqual(SAMPLE);
  });
  it("FR_SET_04_signOutOthers_on_an_empty_list_is_empty", () => {
    expect(signOutOthers([], "a")).toEqual([]);
  });
  it("FR_SET_04_signOutOthers_trusts_the_given_id_not_the_current_flag", () => {
    expect(signOutOthers(SAMPLE, "c").map((s) => s.id)).toEqual(["c"]);
  });
});

describe("FR_SET_04 properties", () => {
  const ids = fc.uniqueArray(fc.string({ minLength: 1, maxLength: 6 }), { maxLength: 8 });
  it("FR_SET_04_property_lists_never_gain_entries_and_current_survives", () => {
    fc.assert(
      fc.property(
        ids,
        fc.string({ maxLength: 6 }),
        fc.string({ maxLength: 6 }),
        (list, cur, pick) => {
          const sessions = list.map((id) => mk(id, id === cur));
          const one = signOutOne(sessions, pick);
          const others = signOutOthers(sessions, cur);
          const all = new Set(list);
          expect(one.length).toBeLessThanOrEqual(sessions.length);
          expect(others.length).toBeLessThanOrEqual(sessions.length);
          for (const s of [...one, ...others]) expect(all.has(s.id)).toBe(true);
          if (all.has(cur)) expect(others.map((s) => s.id)).toContain(cur);
          else expect(others).toEqual(sessions);
        },
      ),
    );
  });
});
