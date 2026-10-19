// @vitest-environment happy-dom
// LIVE-HOME (Opus follow-up, BQ-SIGNIN-4): the remembered Quick / Thinking choice never puts an email in storage.
import { afterEach, describe, expect, it } from "vitest";
import { readEffort, writeEffort } from "./effortStore";

afterEach(() => window.localStorage.clear());

describe("LIVE-HOME effort store keys", () => {
  it("LIVE-HOME the choice is remembered per email and no key or value holds the address", () => {
    writeEffort("Riya.Sharma@example.org", "quick");
    expect(readEffort("riya.sharma@example.org")).toBe("quick");
    expect(readEffort("someone.else@example.org")).toBe("thinking");
    const stored =
      Object.keys(window.localStorage).join("|") + Object.values(window.localStorage).join("|");
    expect(stored).not.toMatch(/riya|sharma|example|@/i);
  });
});
