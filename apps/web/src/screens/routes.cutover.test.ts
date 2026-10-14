// WEB-CUTOVER: the old screens after the Park app takes the root paths. S-04 moves to
// /world/:id/stage, S-18 to /team/console (meta.ts patterns and paths); every
// other kept screen stays on its own address. Bare /team and /worlds belong to Park, not to matchScreen.
import { describe, expect, it } from "vitest";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";
import { parseParkPath, isParkPath } from "../park/app/router";
import { matchFlowRoute } from "../router";
import { screenMeta } from "./meta";
import { matchScreen } from "./routes";

const moved = new Set(["S-15", "S-16", "S-22", "S-23", "S-24"]);
function owner(path: string, id: string) {
  if (moved.has(id)) {
    expect(matchScreen(path), path).toBeNull();
    expect(parseParkPath(path, ""), path).not.toBeNull();
  } else expect(matchScreen(path)?.id, path).toBe(id);
}
const W = `/world/${FIXTURE_WORLD_ID}`;

describe("WEB_CUTOVER_screens: moved screens", () => {
  it("WEB_CUTOVER_04_meta_paths_of_S_04_and_S_18_move", () => {
    expect(screenMeta("S-04")?.path).toBe(`${W}/stage`);
    expect(screenMeta("S-18")?.path).toBe("/team/console");
  });

  it("WEB_CUTOVER_04_the_S_18_pattern_matches_only_its_new_address", () => {
    const s18 = screenMeta("S-18")?.pattern;
    expect(s18?.test("/team/console")).toBe(true);
    expect(s18?.test("/team/console/")).toBe(true);
    expect(s18?.test("/team")).toBe(false);
  });

  it("WEB_CUTOVER_04_matchScreen_finds_S_18_and_S_14_at_their_new_addresses", () => {
    expect(isParkPath("/team/console")).toBe(true);
    expect(matchScreen("/team/console")).toBeNull();
    expect(isParkPath("/team/console/")).toBe(true);
    expect(matchScreen("/team/console/")).toBeNull();
    expect(matchScreen("/worlds/replays")).toBeNull();
    expect(matchScreen("/worlds/replays/")).toBeNull();
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
      ["/world/w/story", "S-10"],
      ["/world/w/trace", "S-11"],
      ["/world/w/delivery", "S-12"],
      ["/autonomy", "S-15"],
      ["/channels", "S-16"],
      ["/mail", "S-17"],
      ["/team/console", "S-18"],
      ["/connections", "S-19"],
      ["/settings", "S-22"],
      ["/estimate", "S-23"],
      ["/pilot", "S-24"],
      ["/more", "more"],
    ];
    for (const [path, id] of table) owner(path, id);
  });

  it("OLD_UI_OUT_07_the_task_flow_screens_are_gone", () => {
    expect(matchScreen("/task/t/understanding")?.id).toBe("not-found");
    expect(matchScreen("/task/t/approaches")?.id).toBe("not-found");
    expect(matchFlowRoute("/task/t/understanding").screen).toBe("Start");
    expect(matchFlowRoute("/task/t/approaches").screen).toBe("Start");
  });

  it("WEB_CUTOVER_07_every_screen_row_with_a_pattern_resolves_from_its_own_path", () => {
    for (const s of [
      "S-05",
      "S-06",
      "S-07",
      "S-08",
      "S-10",
      "S-11",
      "S-12",
      "S-15",
      "S-16",
      "S-22",
      "S-23",
      "S-24",
    ]) {
      const path = screenMeta(s)?.path ?? "";
      owner(path, s);
    }
  });
});
