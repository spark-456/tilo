// @vitest-environment happy-dom
// FR-SET-01 (AGY-WEB-4): the saved Profile form persists per user. The store is a fixture store: it writes
// to localStorage under a key per user and always keeps an in-memory copy, so a blocked or throwing
// localStorage (private mode) still lets Save persist for the session. Nothing is sent to a server.
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearProfileStore, loadProfile, profileKey, saveProfile } from "./profileStore";

const FORM = {
  name: "Ada Lovelace",
  email: "ada@example.test",
  title: "Analyst",
  tz: "Europe/London (GMT+1)",
  lang: "English",
  hours: "09:00 to 17:00",
};

beforeEach(() => {
  window.localStorage.clear();
  clearProfileStore();
});
afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  clearProfileStore();
});

describe("FR_SET_01_profile_store", () => {
  it("test_FR_SET_01_nothing_saved_loads_null", () => {
    expect(loadProfile("a@x.test")).toBeNull();
  });

  it("test_FR_SET_01_saved_values_round_trip_and_are_keyed_per_user", () => {
    saveProfile("a@x.test", FORM);
    expect(loadProfile("a@x.test")).toEqual(FORM);
    expect(loadProfile("b@x.test"), "another user sees nothing").toBeNull();
    expect(profileKey("a@x.test")).not.toBe(profileKey("b@x.test"));
    expect(window.localStorage.getItem(profileKey("a@x.test"))).not.toBeNull();
  });

  it("test_FR_SET_01_a_throwing_localStorage_falls_back_to_memory_without_throwing", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => saveProfile("a@x.test", FORM)).not.toThrow();
    expect(loadProfile("a@x.test")).toEqual(FORM);
    expect(loadProfile("b@x.test")).toBeNull();
  });

  it("test_FR_SET_01_a_corrupt_or_foreign_stored_value_is_ignored", () => {
    window.localStorage.setItem(profileKey("a@x.test"), "{not json");
    expect(loadProfile("a@x.test")).toBeNull();
    window.localStorage.setItem(profileKey("a@x.test"), JSON.stringify({ name: 7, extra: "x" }));
    expect(loadProfile("a@x.test")).toBeNull();
  });

  it("test_FR_SET_01_property_any_saved_form_reads_back_unchanged", () => {
    const text = fc.string({ maxLength: 40 });
    fc.assert(
      fc.property(
        fc.record({
          name: text,
          email: text,
          title: text,
          tz: text,
          lang: text,
          hours: text,
        }),
        fc.string({ minLength: 1, maxLength: 20 }),
        (form, user) => {
          saveProfile(user, form);
          expect(loadProfile(user)).toEqual(form);
        },
      ),
      { numRuns: 40 },
    );
  });
});
