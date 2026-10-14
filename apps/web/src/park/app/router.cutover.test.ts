// WEB-CUTOVER: the Park router at the ROOT paths (docs/web-app-rebuild-plan.md sections 1, 3, 8).
// Pinned surface, park/app/router.ts (names and signatures unchanged):
//   parseParkPath(pathname, search): ParkRoute | null   handles the root form and the /park/<page> alias
//   parkPath(page, params?): string                      WRITES root paths
//   isParkPath(pathname): boolean                        true for every root Park path and /park, /park/*
// Paths that stay with the old app (/world/:id/stage, /team/console, /worlds/replays, ...) are not Park paths.
import { describe, expect, it } from "vitest";
import { PAGE_IDS, type PageId, type Params } from "./AppCtx";
import { isParkPath, legacyTarget, parkPath, parseParkPath } from "./router";

describe("WEB_CUTOVER_router: root paths resolve to Park pages", () => {
  it("WEB_CUTOVER_01_root_paths_resolve_to_park_pages", () => {
    const table: ReadonlyArray<readonly [string, PageId]> = [
      ["/", "home"],
      ["/worlds", "worlds"],
      ["/worlds/", "worlds"],
      ["/team", "team"],
      ["/team/", "team"],
      ["/connectors", "connectors"],
      ["/connectors/", "connectors"],
      ["/skills", "skills"],
      ["/skills/", "skills"],
      ["/agenda", "agenda"],
      ["/agenda/", "agenda"],
      ["/ledger", "ledger"],
      ["/ledger/", "ledger"],
      ["/profile", "profile"],
      ["/profile/", "profile"],
    ];
    for (const [path, page] of table) {
      expect(parseParkPath(path, ""), path).toEqual({ page, params: {} });
    }
  });

  it("WEB_CUTOVER_01_world_takes_exactly_one_url_decoded_segment", () => {
    expect(parseParkPath("/world/k1", "")).toEqual({ page: "world", params: { id: "k1" } });
    expect(parseParkPath("/world/k1/", "")).toEqual({ page: "world", params: { id: "k1" } });
    expect(parseParkPath("/world/Zo%C3%AB%20K", "")?.params).toEqual({ id: "Zoë K" });
    expect(parseParkPath("/world/a%2Fb", "")?.params).toEqual({ id: "a/b" });
    expect(parseParkPath("/world/%E6%97%A5%E6%9C%AC", "")?.params).toEqual({ id: "日本" });
  });

  it("WEB_CUTOVER_01_world_with_no_id_extra_segments_or_a_malformed_escape_is_not_a_route", () => {
    for (const path of [
      "/world",
      "/world/",
      "/world/k1/stage",
      "/world/k1/story",
      "/world/k1/extra/more",
      "/world/%E0",
      "/world/%E0%A4%A",
    ]) {
      expect(parseParkPath(path, ""), path).toBeNull();
    }
  });

  it("WEB_CUTOVER_01_query_rules_are_unchanged_at_the_root", () => {
    expect(parseParkPath("/skills", "?id=sk2")).toEqual({ page: "skills", params: { id: "sk2" } });
    expect(parseParkPath("/team", "?focus=share")).toEqual({
      page: "team",
      params: { focus: "share" },
    });
    expect(parseParkPath("/profile", "?tab=notifications")).toEqual({
      page: "profile",
      params: { tab: "notifications" },
    });
    // Anything else is dropped, and a known name on another page is dropped too.
    expect(parseParkPath("/", "?x=1")).toEqual({ page: "home", params: {} });
    expect(parseParkPath("/ledger", "?id=sk2")).toEqual({ page: "ledger", params: {} });
    expect(parseParkPath("/skills", "?focus=share&x=1")).toEqual({ page: "skills", params: {} });
    expect(parseParkPath("/world/k1", "?id=sk2")).toEqual({ page: "world", params: { id: "k1" } });
  });

  it("WEB_CUTOVER_01_paths_that_are_not_park_pages_parse_to_null", () => {
    for (const path of [
      "/nope",
      "/world/w/stage",
      "/worlds/replays",
      "/team/console",
      "/needs-you",
      "/task/t/understanding",
      "/skills/extra",
    ]) {
      expect(parseParkPath(path, ""), path).toBeNull();
    }
  });
});

describe("WEB_CUTOVER_router: /park/<page> keeps working as an alias", () => {
  it("WEB_CUTOVER_02_the_park_prefix_is_an_alias_for_every_page", () => {
    const table: ReadonlyArray<readonly [string, PageId]> = [
      ["/park", "home"],
      ["/park/", "home"],
      ["/park/home", "home"],
      ["/park/home/", "home"],
      ["/park/worlds", "worlds"],
      ["/park/skills", "skills"],
      ["/park/ledger", "ledger"],
      ["/park/agenda", "agenda"],
      ["/park/team", "team"],
      ["/park/profile", "profile"],
      ["/park/connectors", "connectors"],
    ];
    for (const [path, page] of table) {
      expect(parseParkPath(path, ""), path).toEqual({ page, params: {} });
    }
    expect(parseParkPath("/park/world/k1", "")).toEqual({ page: "world", params: { id: "k1" } });
    expect(parseParkPath("/park/skills", "?id=sk2")?.params).toEqual({ id: "sk2" });
  });

  it("WEB_CUTOVER_02_an_unknown_park_page_is_not_a_route_but_is_still_a_park_path", () => {
    for (const path of [
      "/park/unknown-page",
      "/park/home/extra",
      "/park/world",
      "/park/world/%E0",
    ]) {
      expect(parseParkPath(path, ""), path).toBeNull();
      expect(isParkPath(path), path).toBe(true); // the Park NotFound page shows, not the old app
    }
  });
});

describe("WEB_CUTOVER_router: parkPath writes root paths", () => {
  it("WEB_CUTOVER_03_parkPath_writes_root_paths", () => {
    const table: ReadonlyArray<readonly [PageId, Params, string]> = [
      ["home", {}, "/"],
      ["worlds", {}, "/worlds"],
      ["world", { id: "k1" }, "/world/k1"],
      ["world", {}, "/worlds"],
      ["skills", {}, "/skills"],
      ["ledger", {}, "/ledger"],
      ["agenda", {}, "/agenda"],
      ["team", {}, "/team"],
      ["profile", {}, "/profile"],
      ["connectors", {}, "/connectors"],
    ];
    for (const [page, params, path] of table) {
      expect(parkPath(page, params), `${page} ${JSON.stringify(params)}`).toBe(path);
    }
  });

  it("WEB_CUTOVER_03_world_id_is_encoded_and_the_page_query_is_kept", () => {
    expect(parkPath("world", { id: "a/b c" })).toBe(`/world/${encodeURIComponent("a/b c")}`);
    expect(parkPath("world", { id: "Zoë" })).toBe("/world/Zo%C3%AB");
    expect(parkPath("skills", { id: "x" })).toBe("/skills?id=x");
    expect(parkPath("team", { focus: "share" })).toBe("/team?focus=share");
    expect(parkPath("profile", { tab: "notifications" })).toBe("/profile?tab=notifications");
    // Other params are dropped, as today.
    expect(parkPath("home", { id: "x" })).toBe("/");
    expect(parkPath("ledger", { id: "x" })).toBe("/ledger");
    expect(parkPath("skills", { tab: "x" })).toBe("/skills");
  });

  it("WEB_CUTOVER_03_parkPath_and_parseParkPath_round_trip_and_never_write_the_alias", () => {
    const cases: ReadonlyArray<readonly [PageId, Params]> = [
      ...PAGE_IDS.filter((p) => p !== "world").map((p) => [p, {}] as const),
      ["world", { id: "k1" }],
      ["world", { id: "Zoë K/1" }],
      ["skills", { id: "sk2" }],
      ["team", { focus: "share" }],
      ["profile", { tab: "notifications" }],
    ];
    for (const [page, params] of cases) {
      const written = parkPath(page, params);
      expect(written.startsWith("/park"), written).toBe(false);
      const q = written.indexOf("?");
      const path = q < 0 ? written : written.slice(0, q);
      const search = q < 0 ? "" : written.slice(q);
      expect(parseParkPath(path, search), written).toEqual({ page, params });
      expect(isParkPath(path), written).toBe(true);
    }
  });
});

describe("WEB_CUTOVER_router: isParkPath splits the two apps", () => {
  it("WEB_CUTOVER_03_isParkPath_is_true_for_every_root_park_path_and_the_alias", () => {
    for (const path of [
      "/",
      "/worlds",
      "/worlds/",
      "/world/k1",
      "/world/k1/",
      "/world/Zo%C3%AB%20K",
      "/team",
      "/connectors",
      "/skills",
      "/agenda",
      "/ledger",
      "/profile",
      "/settings",
      "/park",
      "/park/",
      "/park/home",
      "/park/worlds",
      "/park/world/k1",
      "/park/unknown-page",
    ]) {
      expect(isParkPath(path), path).toBe(true);
    }
  });

  it("WEB_CUTOVER_03_isParkPath_is_false_for_everything_that_stays_with_the_old_app", () => {
    for (const path of [
      "/world/w/stage",
      "/world/w/story",
      "/world/w/trace",
      "/world/w/delivery",
      "/world/w/inspect/B1",
      "/team/console",
      "/worlds/replays",
      "/task/t/understanding",
      "/task/t/approaches",
      "/needs-you",
      "/needs-you/gate",
      "/needs-you/consent",
      "/meeting",
      "/library/artifacts",
      "/autonomy",
      "/channels",
      "/mail",
      "/connections",
      "/estimate",
      "/pilot",
      "/meetings",
      "/plate",
      "/pinboards",
      "/calendar",
      "/more",
      "/screens",
      "/parkour",
      "/parks/home",
    ]) {
      // OLD-UI-OUT.md Wave 4 transfers these exact addresses to Park.
      expect(isParkPath(path), path).toBe(
        ["/autonomy", "/channels", "/settings", "/estimate", "/pilot"].includes(path),
      );
    }
  });
});

describe("OLD_UI_OUT_3_legacy: removed old addresses are answered by the Park page that took their function", () => {
  it.each([
    ["/library/artifacts", "/library"],
    ["/meeting", "/agenda"],
    ["/meetings", "/agenda"],
    ["/meetings/mt_q4_plan", "/agenda"],
    ["/pinboards", "/agenda"],
    ["/calendar", "/agenda"],
    ["/plate", "/"],
    ["/worlds/replays", "/worlds"],
  ])("OLD_UI_OUT_3_legacy_%s_goes_to_%s", (from, to) => {
    expect(legacyTarget(from)).toBe(to);
    expect(legacyTarget(`${from}/`)).toBe(to);
  });

  it("OLD_UI_OUT_3_legacy_leaves_every_current_address_alone", () => {
    for (const path of ["/", "/library", "/agenda", "/worlds", "/world/w1", "/more", "/autonomy"]) {
      expect(legacyTarget(path), path).toBeNull();
    }
  });
});
