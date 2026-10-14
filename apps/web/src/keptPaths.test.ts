// WEB-CUTOVER: `isKeptPath` is the one list of addresses the old app owns. Everything else is the Park app
// (its own pages, or its "Page not found"). The list must agree with the old app's own tables: every
// concrete `path` and `pattern` example in screens/meta.ts and the flow routes is kept; S-01's `/` is the Park
// Home now, so it is not.
import { describe, expect, it } from "vitest";
import { isKeptPath } from "./keptPaths";
import { matchFlowRoute } from "./router";
import { SCREENS } from "./screens/meta";

const KEPT = [
  "/start",
  "/task/t1/understanding",
  "/task/t1/approaches",
  "/meeting",
  "/library",
  "/library/artifacts",
  "/autonomy",
  "/channels",
  "/mail",
  "/connections",
  "/settings",
  "/estimate",
  "/pilot",
  "/meetings",
  "/meetings/m1",
  "/plate",
  "/pinboards",
  "/calendar",
  "/more",
  "/worlds/replays",
  "/team/console",
  "/screens",
  "/screens/cards",
  "/dev/components",
];

// OLD-UI-OUT-2: a world's stage and lenses and the Needs-you pages are Park pages (worldView/routes.ts).
const MOVED = [
  "/world/w1/stage",
  "/world/w1/story",
  "/world/w1/trace",
  "/world/w1/delivery",
  "/world/w1/inspect/B1",
  "/needs-you",
  "/needs-you/gate",
  "/needs-you/consent",
];
const MOVED_SCREENS = new Set(["S-04", "S-05", "S-06", "S-07", "S-08", "S-10", "S-11", "S-12"]);

describe("OLD-UI-OUT-2_kept_paths: the moved addresses are Park pages", () => {
  it.each(MOVED)("OLD_UI_OUT_2_kept_paths_%s_is_not_kept", (path) => {
    expect(isKeptPath(path)).toBe(false);
    expect(isKeptPath(`${path}/`)).toBe(false);
  });
});

describe("WEB_CUTOVER_kept_paths: the addresses the old app owns", () => {
  it.each(KEPT)("WEB_CUTOVER_kept_paths_%s_is_kept", (path) => {
    expect(isKeptPath(path)).toBe(true);
  });

  it.each(KEPT)("WEB_CUTOVER_kept_paths_%s_with_a_trailing_slash_is_kept", (path) => {
    expect(isKeptPath(`${path}/`)).toBe(true);
  });

  it("WEB_CUTOVER_kept_paths_every_screen_path_and_pattern_example_in_meta_is_kept", () => {
    const examples: string[] = [];
    for (const s of SCREENS) {
      if (s.id === "S-01") continue; // `/` is the Park Home since WEB-CUTOVER
      if (MOVED_SCREENS.has(s.id)) continue; // OLD-UI-OUT-2: Park pages
      if (s.path !== null) examples.push(s.path);
    }
    expect(examples.length).toBeGreaterThan(10);
    for (const path of examples) expect(isKeptPath(path), path).toBe(true);
    // every pattern accepts its own example, and the example is kept (patterns are what the router matches)
    for (const s of SCREENS) {
      if (!s.pattern || s.path === null) continue;
      expect(s.pattern.test(s.path), `${s.id} pattern matches its path`).toBe(true);
      expect(isKeptPath(s.path), s.id).toBe(true);
    }
  });

  it("WEB_CUTOVER_kept_paths_every_flow_route_address_is_kept", () => {
    for (const path of [
      "/task/abc/understanding",
      "/task/abc/approaches",
      "/task/a%20b/understanding",
    ]) {
      expect(matchFlowRoute(path).screen, path).not.toBe("Start");
      expect(isKeptPath(path), path).toBe(true);
    }
  });

  it.each([
    "/",
    "/xyz",
    "/world/x/unknown",
    "/world/",
    "/world",
    "/start/x",
    "/team/x",
    "/task/t1",
    "/task/t1/other",
    "/worlds/other",
    "/needs-you/other",
    "/library/other",
    "/meetings/a/b",
    "/world/w/inspect",
    "/world/w/inspect/B1/extra",
    "/parkour",
    "/parks/home",
    "/park/home",
    "/worlds",
    "/team",
    "/connectors",
    "",
  ])("WEB_CUTOVER_kept_paths_%j_is_not_kept", (path) => {
    expect(isKeptPath(path)).toBe(false);
  });
});
