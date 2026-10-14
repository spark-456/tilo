// OLD-UI-OUT-2: the addresses of a world's lenses and of the Needs-you page.
import { describe, expect, it } from "vitest";
import { inspectPath, lensPath, overviewPath, parseViewPath, viewTitle } from "./routes";

describe("OLD_UI_OUT_2_routes: lens, inspect and needs-you addresses", () => {
  it.each(["stage", "story", "trace", "delivery"] as const)("the %s lens parses", (lens) => {
    expect(parseViewPath(`/world/w1/${lens}`)).toEqual({ kind: "lens", worldId: "w1", lens });
    expect(parseViewPath(`/world/w1/${lens}/`)).toEqual({ kind: "lens", worldId: "w1", lens });
  });

  it("inspect parses and URL-decodes both ids", () => {
    expect(parseViewPath("/world/w%201/inspect/B1")).toEqual({
      kind: "inspect",
      worldId: "w 1",
      itemId: "B1",
    });
  });

  it("the needs-you sheets parse", () => {
    expect(parseViewPath("/needs-you")).toEqual({ kind: "needs", sheet: "queue" });
    expect(parseViewPath("/needs-you/gate")).toEqual({ kind: "needs", sheet: "gate" });
    expect(parseViewPath("/needs-you/consent/")).toEqual({ kind: "needs", sheet: "consent" });
  });

  it.each([
    "/",
    "/world/w1",
    "/world/w1/unknown",
    "/world/w1/inspect",
    "/world/w1/inspect/B1/extra",
    "/world/%E0/stage",
    "/world/w1/inspect/%E0",
    "/needs-you/other",
    "/worlds",
  ])("%j is no view", (path) => {
    expect(parseViewPath(path)).toBeNull();
  });

  it("the path builders round-trip through the parser", () => {
    expect(parseViewPath(lensPath("w 1", "story"))).toEqual({
      kind: "lens",
      worldId: "w 1",
      lens: "story",
    });
    expect(parseViewPath(inspectPath("w1", "a/b"))).toEqual({
      kind: "inspect",
      worldId: "w1",
      itemId: "a/b",
    });
    expect(overviewPath("w 1")).toBe("/world/w%201");
  });

  it("titles read as the page names", () => {
    expect(viewTitle({ kind: "lens", worldId: "w", lens: "story" })).toBe("Story");
    expect(viewTitle({ kind: "needs", sheet: "queue" })).toBe("Needs you");
    expect(viewTitle({ kind: "needs", sheet: "gate" })).toBe("Approval gate");
  });
});
