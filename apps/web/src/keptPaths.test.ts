// WEB-CUTOVER: `isKeptPath` is the one list of addresses the old app owns. Everything else is the Park app
// (its own pages, or its "Page not found"). The list must agree with the old app's own tables: every
// concrete `path` and `pattern` example in screens/meta.ts and the flow routes is kept; S-01's `/` is the Park
// Home now, so it is not.
import { describe, expect, it } from "vitest";
import { isKeptPath, isRetiredFlowPath } from "./keptPaths";
import { isParkPath } from "./park/app/router";
import { matchFlowRoute } from "./router";
import { SCREENS } from "./screens/meta";

// Reference: agy-bridge/tasks/OLD-UI-OUT.md Wave 4.
const MOVED = new Set(["/autonomy", "/channels", "/settings", "/estimate", "/pilot", "/mail", "/connections", "/more", "/team/console"]);
const ownership = (path: string) => {
  const moved = MOVED.has(path.replace(/\/$/, ""));
  expect(isKeptPath(path), path).toBe(!moved);
  if (moved) expect(isParkPath(path), path).toBe(true);
};
const KEPT = [
  "/world/w1/stage",
  "/world/w1/story",
  "/world/w1/trace",
  "/world/w1/delivery",
  "/world/w1/inspect/B1",
  "/needs-you",
  "/needs-you/gate",
  "/needs-you/consent",
  "/autonomy",
  "/channels",
  "/mail",
  "/connections",
  "/estimate",
  "/pilot",
  "/more",
  "/team/console",
  "/settings",
  "/screens",
  "/screens/cards",
  "/dev/components",
];

describe("WEB_CUTOVER_kept_paths: the addresses the old app owns", () => {
  it.each(KEPT)("WEB_CUTOVER_kept_paths_%s_is_kept", (path) => {
    ownership(path);
  });

  it.each(KEPT)("WEB_CUTOVER_kept_paths_%s_with_a_trailing_slash_is_kept", (path) => {
    ownership(`${path}/`);
  });

  it("WEB_CUTOVER_kept_paths_every_screen_path_and_pattern_example_in_meta_is_kept", () => {
    const examples: string[] = [];
    for (const s of SCREENS) {
      if (s.id === "S-01" || s.id === "S-22") continue; // UI-10 W7: Home and Settings use Park.
      if (s.path !== null) examples.push(s.path);
    }
    expect(examples.length).toBeGreaterThan(12);
    for (const path of examples) ownership(path);
    // every pattern accepts its own example, and the example is kept (patterns are what the router matches)
    for (const s of SCREENS) {
      if (!s.pattern || s.path === null) continue;
      expect(s.pattern.test(s.path), `${s.id} pattern matches its path`).toBe(true);
      ownership(s.path);
    }
  });

  it("WEB_CUTOVER_kept_paths_every_flow_route_address_is_kept", () => {
    for (const path of ["/world/abc/stage", "/world/q%201%2F2/stage"]) {
      expect(matchFlowRoute(path).screen, path).not.toBe("Start");
      ownership(path);
    }
  });

  it.each([
    "/",
    "/xyz",
    "/world/x/unknown",
    "/world/",
    "/world",
    "/start",
    "/start/x",
    "/team/x",
    "/task/t1",
    "/task/t1/understanding",
    "/task/t1/approaches",
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
    "/settings",
    "/settings/",
    "",
  ])("WEB_CUTOVER_kept_paths_%j_is_not_kept", (path) => {
    expect(isKeptPath(path)).toBe(false);
  });
});

describe("OLD_UI_OUT_retired_flow_paths: the old Start, Understanding and Approaches addresses", () => {
  it.each([
    "/start",
    "/start/",
    "/task/t1/understanding",
    "/task/t1/approaches",
    "/task/t1/approaches/",
  ])("SIMPLE_RUN_1_%s_is_retired", (path) => {
    expect(isRetiredFlowPath(path)).toBe(true);
  });

  it.each(["/start/x", "/world/w/stage", "/task/t1", "/task/t1/other", "/worlds"])(
    "SIMPLE_RUN_1_%s_is_not_retired",
    (path) => {
      expect(isRetiredFlowPath(path)).toBe(false);
    },
  );
});

describe("OLD_UI_OUT_3_removed_addresses: Library, Meetings, plate, pinboards, calendar and replays are Park's", () => {
  it.each([
    "/library",
    "/library/artifacts",
    "/meeting",
    "/meetings",
    "/meetings/m1",
    "/plate",
    "/pinboards",
    "/calendar",
    "/worlds/replays",
  ])("OLD_UI_OUT_3_%s_is_not_kept", (path) => {
    expect(isKeptPath(path)).toBe(false);
  });
});
