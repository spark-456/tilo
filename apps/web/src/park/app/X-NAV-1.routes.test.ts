import { describe, expect, it } from "vitest";
import { PAGE_IDS } from "./AppCtx";
import { PAGES } from "./pages";
import { parkPath, parseParkPath } from "./router";

// Supervisor X-NAV-1: the sidebar's existing destinations must resolve in Park.
// These are the addresses in screens/meta.ts and screens/PrimaryNav.tsx.
const SIDEBAR_PATHS = [
  ["Home", "/"],
  ["World", "/world/northline/stage"],
  ["Story", "/world/northline/story"],
  ["Needs you", "/needs-you"],
  ["Library", "/library"],
  ["More", "/more"],
] as const;

describe("X_NAV_1 Park route coverage", () => {
  for (const [label, path] of SIDEBAR_PATHS) {
    it(`X_NAV_1 ${label} resolves to a registered Park page`, () => {
      const route = parseParkPath(path, "");
      expect(route, `${label} at ${path} needs its OLD-UI Park page`).not.toBeNull();
      if (route) expect(PAGES).toHaveProperty(route.page);
    });
  }

  it("X_NAV_1 every registered Park page has a round-trip root and alias", () => {
    for (const page of PAGE_IDS) {
      const path = parkPath(page, page === "world" ? { id: "northline" } : {});
      expect(parseParkPath(path, "")?.page).toBe(page);
      expect(parseParkPath(`/park${path === "/" ? "/home" : path}`, "")?.page).toBe(page);
      expect(PAGES).toHaveProperty(page);
    }
  });
});
