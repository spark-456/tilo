// WEB-CUTOVER: the old screens after the Park app takes the root paths. S-04 moves to
// /world/:id/stage, S-14 to /worlds/replays, S-18 to /team/console (meta.ts patterns and paths); every
// other kept screen stays on its own address. Bare /team and /worlds belong to Park, not to matchScreen.
import { describe, expect, it } from "vitest";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";
import { parseParkPath } from "../park/app/router";
import { matchFlowRoute } from "../router";
import { screenMeta } from "./meta";
import { matchScreen } from "./routes";

const moved = new Set(["S-15", "S-16", "S-17", "S-18", "S-19", "S-22", "S-23", "S-24", "more"]);
function owner(path: string, id: string) {
  if (moved.has(id)) {
    expect(matchScreen(path), path).toBeNull();
    expect(parseParkPath(path, ""), path).not.toBeNull();
  } else expect(matchScreen(path)?.id, path).toBe(id);
}
const W = `/world/${FIXTURE_WORLD_ID}`;

describe("WEB_CUTOVER_screens: moved screens", () => {
  it("WEB_CUTOVER_04_meta_paths_of_S_04_S_14_and_S_18_move", () => {
    expect(screenMeta("S-04")?.path).toBe(`${W}/stage`);
    expect(screenMeta("S-14")?.path).toBe("/worlds/replays");
    expect(screenMeta("S-18")?.path).toBe("/team/console");
  });

  it("WEB_CUTOVER_04_the_S_14_and_S_18_patterns_match_only_their_new_addresses", () => {
    const s14 = screenMeta("S-14")?.pattern;
    const s18 = screenMeta("S-18")?.pattern;
    expect(s14?.test("/worlds/replays")).toBe(true);
    expect(s14?.test("/worlds/replays/")).toBe(true);
    expect(s14?.test("/worlds")).toBe(false);
    expect(s18?.test("/team/console")).toBe(true);
    expect(s18?.test("/team/console/")).toBe(true);
    expect(s18?.test("/team")).toBe(false);
  });

  it("WEB_CUTOVER_04_matchScreen_finds_S_18_and_S_14_at_their_new_addresses", () => {
    owner("/team/console", "S-18");
    owner("/team/console/", "S-18");
    expect(matchScreen("/worlds/replays")?.id).toBe("S-14");
    expect(matchScreen("/worlds/replays/")?.id).toBe("S-14");
  });

  it("WEB_CUTOVER_04_bare_team_and_worlds_are_not_matched_by_matchScreen", () => {
    expect(matchScreen("/team")).toBeNull();
    expect(matchScreen("/worlds")).toBeNull();
  });

  it("WEB_CUTOVER_04_the_stage_is_a_flow_route_not_a_screen_row", () => {
    const path = screenMeta("S-04")?.path ?? "";
    expect(matchScreen(path)).toBeNull();
    expect(matchFlowRoute(path)).toEqual({ screen: "World", worldId: FIXTURE_WORLD_ID });
    expect(matchScreen("/world/w/stage")).toBeNull();
  });
});

describe("WEB_CUTOVER_screens: kept screens stay reachable on their own paths", () => {
  it("WEB_CUTOVER_07_every_kept_screen_resolves_from_its_address", () => {
    const table: ReadonlyArray<readonly [string, string]> = [
      ["/world/w/inspect/B1", "S-05"],
      ["/needs-you", "S-06"],
      ["/needs-you/gate", "S-07"],
      ["/needs-you/consent", "S-08"],
      ["/meeting", "S-09"],
      ["/world/w/story", "S-10"],
      ["/world/w/trace", "S-11"],
      ["/world/w/delivery", "S-12"],
      ["/library", "S-13"],
      ["/worlds/replays", "S-14"],
      ["/autonomy", "S-15"],
      ["/channels", "S-16"],
      ["/mail", "S-17"],
      ["/team/console", "S-18"],
      ["/connections", "S-19"],
      ["/library/artifacts", "S-21"],
      ["/settings", "S-22"],
      ["/estimate", "S-23"],
      ["/pilot", "S-24"],
      ["/meetings", "S-26"],
      ["/plate", "S-27"],
      ["/pinboards", "S-28"],
      ["/calendar", "S-29"],
      ["/more", "more"],
    ];
    for (const [path, id] of table) owner(path, id);
  });

  it("WEB_CUTOVER_07_the_task_flow_screens_stay_in_the_flow_shell", () => {
    expect(matchScreen("/task/t/understanding")).toBeNull();
    expect(matchScreen("/task/t/approaches")).toBeNull();
    expect(matchFlowRoute("/task/t/understanding").screen).toBe("Understanding");
    expect(matchFlowRoute("/task/t/approaches").screen).toBe("Approaches");
  });

  it("WEB_CUTOVER_07_every_screen_row_with_a_pattern_resolves_from_its_own_path", () => {
    for (const s of [
      "S-05",
      "S-06",
      "S-07",
      "S-08",
      "S-09",
      "S-10",
      "S-11",
      "S-12",
      "S-13",
      "S-14",
      "S-15",
      "S-16",
      "S-17",
      "S-18",
      "S-19",
      "S-21",
      "S-22",
      "S-23",
      "S-24",
      "S-26",
      "S-27",
      "S-28",
      "S-29",
    ]) {
      const path = screenMeta(s)?.path ?? "";
      owner(path, s);
    }
  });
});
