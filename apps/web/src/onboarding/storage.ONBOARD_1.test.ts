// @vitest-environment happy-dom
// ONBOARD-1 (user-requested, no PRD requirement; BQ-ONBOARD-1): the once-per-user flag. Every read and write is in
// try/catch, so a page whose storage throws still works.
import { afterEach, describe, expect, it, vi } from "vitest";
import { hasSeen, markSeen, userKeyOf } from "./storage";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("ONBOARD_1_storage: once per user", () => {
  it("ONBOARD_1_storage_remembers_per_user_key", () => {
    expect(hasSeen("a")).toBe(false);
    markSeen("a");
    expect(hasSeen("a")).toBe(true);
    expect(hasSeen("b")).toBe(false);
  });

  it("ONBOARD_1_storage_key_is_per_signed_in_person_or_demo", () => {
    expect(userKeyOf({ status: "google", displayName: "Sam", email: "Sam@Example.test" })).toBe(
      "google:sam@example.test",
    );
    expect(userKeyOf({ status: "anonymous" })).toBe("anonymous");
    expect(userKeyOf({ status: "unavailable" })).toBe("demo");
    expect(userKeyOf({ status: "unknown" })).toBe("demo");
    expect(userKeyOf({ status: "google", displayName: null, email: null })).toBe("google:account");
  });

  it("ONBOARD_1_storage_throwing_never_throws", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => markSeen("a")).not.toThrow();
    expect(hasSeen("a")).toBe(false);
  });

  it("ONBOARD_1_storage_missing_localStorage_never_throws", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(() => markSeen("a")).not.toThrow();
    expect(hasSeen("a")).toBe(false);
  });
});
