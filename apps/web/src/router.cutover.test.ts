// WEB-CUTOVER: the live stage (S-04) moves from /world/:id to /world/:id/stage, because /world/:id is now
// the Park World overview. Pinned in src/router.ts: matchFlowRoute and a new export
// `stagePath(worldId: string): string` returning `/world/<encodeURIComponent id>/stage`.
import { describe, expect, it } from "vitest";
import * as router from "./router";
import { matchFlowRoute } from "./router";

describe("WEB_CUTOVER_router: the flow routes", () => {
  it("WEB_CUTOVER_04_the_stage_is_matched_at_world_id_stage", () => {
    expect(matchFlowRoute("/world/w/stage")).toEqual({ screen: "World", worldId: "w" });
    expect(matchFlowRoute("/world/w/stage/")).toEqual({ screen: "World", worldId: "w" });
    expect(matchFlowRoute("/world/w_village_basic/stage")).toEqual({
      screen: "World",
      worldId: "w_village_basic",
    });
    expect(matchFlowRoute("/world/w%201/stage")).toEqual({ screen: "World", worldId: "w 1" });
  });

  it("WEB_CUTOVER_04_a_bare_world_id_is_no_longer_a_flow_route", () => {
    for (const path of ["/world/w", "/world/w/", "/world/w_village_basic"]) {
      expect(matchFlowRoute(path), path).toEqual({ screen: "Start" });
    }
  });

  it("WEB_CUTOVER_04_a_malformed_escape_or_a_deeper_path_is_not_the_stage", () => {
    expect(matchFlowRoute("/world/w%E0/stage")).toEqual({ screen: "Start" });
    expect(matchFlowRoute("/world/w/stage/x")).toEqual({ screen: "Start" });
    expect(matchFlowRoute("/world//stage")).toEqual({ screen: "Start" });
    expect(matchFlowRoute("/world/w/story")).toEqual({ screen: "Start" });
  });

  it("OLD_UI_OUT_04_the_task_flow_routes_are_gone", () => {
    expect(matchFlowRoute("/task/t1/understanding")).toEqual({ screen: "Start" });
    expect(matchFlowRoute("/task/t1/approaches")).toEqual({ screen: "Start" });
    expect(matchFlowRoute("/")).toEqual({ screen: "Start" });
  });
});

describe("WEB_CUTOVER_router: stagePath", () => {
  it("WEB_CUTOVER_04_stagePath_is_exported_and_encodes_the_world_id", () => {
    const stagePath = Reflect.get(router, "stagePath") as ((id: string) => string) | undefined;
    expect(typeof stagePath).toBe("function");
    if (!stagePath) return;
    expect(stagePath("w")).toBe("/world/w/stage");
    expect(stagePath("w_village_basic")).toBe("/world/w_village_basic/stage");
    expect(stagePath("w 1/é")).toBe(`/world/${encodeURIComponent("w 1/é")}/stage`);
  });

  it("WEB_CUTOVER_04_stagePath_round_trips_through_matchFlowRoute", () => {
    const stagePath = Reflect.get(router, "stagePath") as ((id: string) => string) | undefined;
    if (!stagePath) throw new Error("router.ts does not export stagePath");
    for (const id of ["w", "w_village_basic", "w 1", "a/b", "Zoë"]) {
      expect(matchFlowRoute(stagePath(id)), id).toEqual({ screen: "World", worldId: id });
    }
  });
});
