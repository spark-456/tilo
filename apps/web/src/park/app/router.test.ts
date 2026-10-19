// WEB-3a: the pure Park router (plan section 1; README "Routes"); WEB-CUTOVER moved the pages to the root
// paths (router.cutover.test.ts) and kept /park/<page> as an alias, which this file still pins. Pinned surface, in
// park/app/router.ts:
//   parseParkPath(pathname: string, search: string): { page: PageId; params: Params } | null
//   parkPath(page: PageId, params?: Params): string
//   isParkPath(pathname: string): boolean
// Defaults taken where the README is silent (listed in the WEB-3a report):
// - `/park/world` with no id is not a route (null), not the prototype's silent "k1".
// - Only the README's query params are kept: skills `id`, team `focus`, profile `tab`; anything else
//   (and a known name on another page) is dropped. The world id is a path segment, not a query.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { stagePath as appStagePath } from "../../router";
import { PAGE_IDS, type PageId, type Params } from "./AppCtx";
import { adminRedirect } from "./adminRedirect";
import { isParkPath, parkPath, parseParkPath, stagePath } from "./router";

describe("WEB_CUTOVER_router: the Park stagePath is the old app's stagePath", () => {
  it("WEB_CUTOVER_04_stagePath_matches_src_router", () => {
    for (const id of ["w", "w_village_basic", "w 1/é", "100%"]) {
      expect(stagePath(id), id).toBe(appStagePath(id));
    }
  });
});

describe("WEB_3a_router: parseParkPath maps each design route", () => {
  it("WEB_3a_router_every_design_route_maps_to_its_page", () => {
    const table = [
      ["/park", "home"],
      ["/park/", "home"],
      ["/park/home", "home"],
      ["/park/home/", "home"],
      ["/park/worlds", "worlds"],
      ["/park/worlds/", "worlds"],
      ["/park/skills", "skills"],
      ["/park/ledger", "ledger"],
      ["/park/agenda", "agenda"],
      ["/park/team", "team"],
      ["/park/profile", "profile"],
      ["/park/connectors", "connectors"],
      ["/park/connectors/", "connectors"],
    ] as const;
    for (const [path, page] of table) {
      expect(parseParkPath(path, ""), path).toEqual({ page, params: {} });
    }
  });

  it("WEB_3a_router_world_carries_the_id", () => {
    expect(parseParkPath("/park/world/k1", "")).toEqual({ page: "world", params: { id: "k1" } });
    expect(parseParkPath("/park/world/k1/", "")).toEqual({ page: "world", params: { id: "k1" } });
  });

  it("WEB_3a_router_world_id_is_url_decoded", () => {
    expect(parseParkPath("/park/world/Zo%C3%AB%20K", "")?.params).toEqual({ id: "Zoë K" });
    expect(parseParkPath("/park/world/a%2Fb", "")?.params).toEqual({ id: "a/b" });
    expect(parseParkPath("/park/world/%E6%97%A5%E6%9C%AC", "")?.params).toEqual({ id: "日本" });
  });

  it("WEB_3a_router_the_query_names_of_skills_team_and_profile", () => {
    expect(parseParkPath("/park/skills", "?id=sk2")).toEqual({
      page: "skills",
      params: { id: "sk2" },
    });
    expect(parseParkPath("/park/team", "?focus=share")).toEqual({
      page: "team",
      params: { focus: "share" },
    });
    expect(parseParkPath("/park/profile", "?tab=notifications")).toEqual({
      page: "profile",
      params: { tab: "notifications" },
    });
  });

  it("WEB_3a_router_search_may_come_with_or_without_the_question_mark", () => {
    expect(parseParkPath("/park/skills", "id=sk2")).toEqual(
      parseParkPath("/park/skills", "?id=sk2"),
    );
  });

  it("WEB_3a_router_unknown_query_params_are_dropped", () => {
    expect(parseParkPath("/park/home", "?x=1")).toEqual({ page: "home", params: {} });
    expect(parseParkPath("/park/skills", "?id=sk2&x=1&utm=2")).toEqual({
      page: "skills",
      params: { id: "sk2" },
    });
    expect(parseParkPath("/park/world/k1", "?x=1")).toEqual({
      page: "world",
      params: { id: "k1" },
    });
  });

  it("WEB_3a_router_a_known_query_name_on_another_page_is_dropped", () => {
    expect(parseParkPath("/park/skills", "?tab=billing")).toEqual({ page: "skills", params: {} });
    expect(parseParkPath("/park/team", "?id=p1")).toEqual({ page: "team", params: {} });
    expect(parseParkPath("/park/world/k1", "?focus=share")).toEqual({
      page: "world",
      params: { id: "k1" },
    });
  });

  it("WEB_3a_router_query_values_are_decoded", () => {
    expect(parseParkPath("/park/skills", "?id=a%20b%26c")?.params).toEqual({ id: "a b&c" });
  });
});

describe("WEB_3a_router: what is not a Park route", () => {
  it("WEB_3a_router_null_for_anything_that_is_not_a_page", () => {
    const paths = [
      "/world/k1/extra",
      "/home",
      "/parkour",
      "/parks/home",
      "/park/nope",
      "/park/Home",
      "/park/home/extra",
      "/park/worlds/extra",
      "/park/world",
      "/park/world/",
      "/park/world/k1/extra",
      "/park//home",
      "/other/park/home",
    ];
    for (const path of paths) expect(parseParkPath(path, ""), path).toBeNull();
  });

  it("WEB_3a_router_malformed_percent_escape_is_null_and_never_throws", () => {
    for (const path of [
      "/park/world/%",
      "/park/world/%E0%A4%A",
      "/park/world/%zz",
      "/park/world/%E0",
    ]) {
      expect(() => parseParkPath(path, ""), path).not.toThrow();
      expect(parseParkPath(path, ""), path).toBeNull();
    }
  });

  it("WEB_3a_router_a_malformed_escape_in_the_query_does_not_throw", () => {
    expect(() => parseParkPath("/park/skills", "?id=%E0%A4%A")).not.toThrow();
    expect(parseParkPath("/park/skills", "?id=%E0%A4%A")?.page).toBe("skills");
  });
});

describe("WEB_3a_router: parkPath writes the path", () => {
  it("WEB_3a_router_parkPath_writes_each_page_path", () => {
    const table = [
      ["home", "/"],
      ["worlds", "/worlds"],
      ["skills", "/skills"],
      ["ledger", "/ledger"],
      ["agenda", "/agenda"],
      ["team", "/team"],
      ["profile", "/profile"],
      ["connectors", "/connectors"],
    ] as const;
    for (const [page, path] of table) expect(parkPath(page), page).toBe(path);
  });

  it("WEB_3a_router_parkPath_world_puts_the_id_in_the_path", () => {
    expect(parkPath("world", { id: "k1" })).toBe("/world/k1");
    expect(parkPath("world", { id: "a b" })).toBe("/world/a%20b");
    expect(parkPath("world", { id: "a/b" })).toBe("/world/a%2Fb");
  });

  it("WEB_3a_router_parkPath_puts_the_known_params_in_the_query", () => {
    expect(parkPath("skills", { id: "sk2" })).toBe("/skills?id=sk2");
    expect(parkPath("team", { focus: "share" })).toBe("/team?focus=share");
    expect(parkPath("profile", { tab: "notifications" })).toBe("/profile?tab=notifications");
  });

  it("WEB_3a_router_parkPath_drops_params_the_page_does_not_know", () => {
    expect(parkPath("home", { x: "1", id: "k1" })).toBe("/");
    expect(parkPath("skills", { id: "sk2", x: "1" })).toBe("/skills?id=sk2");
    expect(parkPath("ledger", { focus: "share" })).toBe("/ledger");
  });

  it("WEB_3a_router_parkPath_output_is_always_a_safe_path", () => {
    for (const bad of ["a b", "a#b", "a?b", "a&b=c", "100%", "<x>"]) {
      expect(parkPath("world", { id: bad })).not.toMatch(/[ #<>]|\?|&/);
      expect(parkPath("skills", { id: bad })).not.toMatch(/[ #<>]/);
    }
  });
});

describe("WEB_3a_router: isParkPath", () => {
  it("WEB_3a_router_isParkPath_true_under_park", () => {
    for (const p of [
      "/park",
      "/park/",
      "/park/home",
      "/park/world/k1",
      "/park/nope",
      "/park/x/y",
    ]) {
      expect(isParkPath(p), p).toBe(true);
    }
  });

  it("WEB_3a_router_a_trailing_slash_is_replaced_by_the_canonical_address", () => {
    expect(adminRedirect("/world/")).toBe("/world");
    expect(adminRedirect("/worlds/", "?x=1")).toBe("/worlds?x=1");
    expect(adminRedirect("/index.html", "?x=1")).toBe("/?x=1");
  });

  it("WEB_3a_router_isParkPath_false_elsewhere", () => {
    for (const p of [
      "/home",
      "/world",
      "/world/k1/stage",
      "/parkour",
      "/parks",
      "/Park/home",
      "/dev/components",
    ]) {
      expect(isParkPath(p), p).toBe(false);
    }
  });
});

// Ids as people and ids as the wild produce them: spaces, slashes, percent signs, unicode, query characters.
const text = fc.oneof(
  fc.string({ unit: "grapheme", minLength: 1, maxLength: 12 }),
  fc.constantFrom("a b", "a/b", "Zoë", "日本語", "100%", "a?b#c", "a&b=c", "x+y", "%2F", "k 1/2"),
);
const idText = text.filter((s) => s !== "." && s !== "..");

const routeArb: fc.Arbitrary<{ page: PageId; params: Params }> = fc.oneof(
  fc
    .constantFrom<PageId>("home", "worlds", "ledger", "agenda", "connectors")
    .map((page) => ({ page, params: {} })),
  idText.map((id) => ({ page: "world" as const, params: { id } })),
  fc
    .oneof(
      fc.constant({}),
      text.map((id) => ({ id })),
    )
    .map((params) => ({
      page: "skills" as const,
      params,
    })),
  fc
    .oneof(
      fc.constant({}),
      text.map((focus) => ({ focus })),
    )
    .map((params) => ({
      page: "team" as const,
      params,
    })),
  fc
    .oneof(
      fc.constant({}),
      text.map((tab) => ({ tab })),
    )
    .map((params) => ({
      page: "profile" as const,
      params,
    })),
);

const split = (url: string): [string, string] => {
  const i = url.indexOf("?");
  return i < 0 ? [url, ""] : [url.slice(0, i), url.slice(i)];
};

describe("WEB_3a_router: properties", () => {
  it("WEB_3a_router_property_parse_of_parkPath_round_trips", () => {
    fc.assert(
      fc.property(routeArb, ({ page, params }) => {
        const [pathname, search] = split(parkPath(page, params));
        expect(parseParkPath(pathname, search)).toEqual({ page, params });
      }),
    );
  });

  it("WEB_3a_router_property_parseParkPath_never_throws_and_yields_known_pages_only", () => {
    fc.assert(
      fc.property(fc.string(), fc.string(), (pathname, search) => {
        const r = parseParkPath(pathname, search);
        if (r !== null) {
          expect(PAGE_IDS).toContain(r.page);
          for (const k of Object.keys(r.params)) expect(["id", "focus", "tab"]).toContain(k);
        }
      }),
    );
  });

  it("WEB_3a_router_property_every_page_id_has_a_path_that_parses_back", () => {
    for (const page of PAGE_IDS) {
      const params = page === "world" ? { id: "k1" } : {};
      const [pathname, search] = split(parkPath(page, params));
      expect(parseParkPath(pathname, search)?.page).toBe(page);
      expect(isParkPath(pathname)).toBe(true);
    }
  });
});
