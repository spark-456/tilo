import fc from "fast-check";
// @vitest-environment happy-dom
// WEB-5 acceptance, restructured for STUDIO-3 (design/studio-v2 "Tilo S Worlds.dc.html"): one card grid sorted
// needs, working, scheduled, done (the size sections are gone; size is a filter), status tabs All / Working /
// Needs you / Scheduled / Done, the "Find a world" search beside the tabs. The rules that stay: data only from
// useParkApi().getWorlds(app.dec, app.added) and getDecisions(); navigation only app.go; approval only app.decide.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  buttons,
  card,
  cardIds,
  flush,
  hrefOf,
  leaf,
  renderWorlds,
  scaleButton,
  search,
  section,
  spotlight,
  statusTabs,
  tab,
  tabCounts,
  typeInto,
  worldsApi,
} from "../../../../test-support/park/worldsHarness";
import * as fx from "../../api/fixtures";
import { NotBuilt } from "../../api/liveApi";
import type { World } from "../../api/types";

afterEach(cleanup);

const SUBTITLE = "Every bigger job gets its own little city. Here are all of yours.";
const GRID = "Your worlds";
const TABS = ["All", "Working", "Needs you", "Scheduled", "Done"];
/** The fixture list as the grid draws it: needs, working, scheduled, done, each in source order. */
const ALL = [
  "k1",
  "hires",
  "northline",
  "calls",
  "venues",
  "invoice",
  "inbox",
  "pricing",
  "audit",
  "comp",
  "reply",
];
const shown = (c: HTMLElement) => cardIds(c, GRID);
const text = (el: Element | null) => el?.textContent ?? "";
/** Asserts `t` holds the string, or matches the pattern. */
const has = (t: string, w: string | RegExp) =>
  typeof w === "string" ? expect(t).toContain(w) : expect(t).toMatch(w);

describe("WEB_5_worlds: header, search and New world", () => {
  it("TILO_T_STATES_HR1_worlds_use_shared_empty_loading_and_error_states", async () => {
    const pending = worldsApi();
    pending.getWorlds = vi.fn(() => new Promise<never>(() => undefined));
    const loading = await renderWorlds({ api: pending });
    expect(loading.c.querySelector('[data-testid="tt-loading"]')?.textContent).toContain(
      "Loading worlds",
    );

    const failed = worldsApi();
    failed.getWorlds = vi.fn(() => Promise.reject(new Error("offline")));
    const error = await renderWorlds({ api: failed });
    expect(error.c.querySelector('[data-testid="tt-error"]')?.getAttribute("role")).toBe("alert");

    const retryApi = worldsApi();
    const result = await retryApi.getWorlds({}, []);
    const retryPending = new Promise<typeof result>(() => undefined);
    retryApi.getWorlds = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockReturnValueOnce(retryPending);
    const retry = await renderWorlds({ api: retryApi });
    await act(async () => {
      buttons(retry.c, "Try again")[0]?.click();
    });
    await flush();
    expect(retry.c.querySelector('[data-testid="tt-loading"]')).not.toBeNull();

    const empty = await renderWorlds({ api: worldsApi(() => []) });
    expect(empty.c.querySelector('[data-testid="tt-empty"]')).not.toBeNull();
  });

  it("WEB_5_worlds_header_title_total_and_subtitle_verbatim", async () => {
    const { c } = await renderWorlds();
    expect(qa(c, "h1").map(text)).toEqual(["Worlds"]);
    expect(leaf(c, "11 worlds")).not.toBeNull();
    expect(leaf(c, SUBTITLE)?.tagName).toBe("P");
    expect(c.querySelectorAll('[data-testid="park-page-worlds"]')).toHaveLength(1);
  });

  it("WEB_5_worlds_header_renders_before_the_data_arrives", async () => {
    const api = worldsApi();
    api.getWorlds = vi.fn(() => new Promise<never>(() => undefined));
    api.getDecisions = vi.fn(() => new Promise<never>(() => undefined));
    const { c } = await renderWorlds({ api });
    expect(text(q(c, "h1"))).toBe("Worlds");
    expect(c.querySelector('[data-testid="park-page-worlds"]')).not.toBeNull();
  });

  it("WEB_5_worlds_reads_only_through_the_api_with_dec_and_added", async () => {
    const added = [fx.makeWorld("quick", "Compare three suppliers", 1)];
    const r = await renderWorlds({ dec: { depot: true }, added });
    expect(r.api.getWorlds).toHaveBeenCalledWith({ depot: true }, added);
    expect(r.api.getDecisions).toHaveBeenCalled();
    await r.update({ dec: { depot: true, mail: true }, added });
    expect(r.api.getWorlds).toHaveBeenLastCalledWith({ depot: true, mail: true }, added);
  });

  it("WEB_5_worlds_a_not_built_api_says_not_connected_yet", async () => {
    const api = worldsApi();
    api.getWorlds = vi.fn(() => Promise.reject(new NotBuilt("getWorlds")));
    const { c } = await renderWorlds({ api });
    expect(text(c)).toContain("Worlds data is unavailable");
    expect(qa(c, `section[aria-label="${GRID}"] a[href]`)).toHaveLength(0);
    expect(text(q(c, "h1"))).toBe("Worlds");
  });

  it("WEB_5_worlds_live_worlds_and_decisions_show_even_when_the_city_plans_are_not_built", async () => {
    // The live Api serves worlds and decisions but not plans yet: plans only draw City art.
    const api = worldsApi();
    api.getPlans = vi.fn(() => Promise.reject(new NotBuilt("getPlans")));
    const { c } = await renderWorlds({ api });
    expect(text(c)).not.toContain("Worlds data is unavailable");
    expect(shown(c)).toEqual(ALL);
    expect(spotlight(c)).not.toBeNull();
  });

  it("WEB_5_worlds_search_is_named_and_filters_by_name_ignoring_case", async () => {
    const { c } = await renderWorlds();
    expect(search(c).placeholder).toBe("Find a world");
    typeInto(search(c), "INVOICE");
    expect(search(c).value).toBe("INVOICE");
    expect(shown(c)).toEqual(["invoice"]);
    expect(tabCounts(c)).toEqual({ All: 1, Working: 0, "Needs you": 0, Scheduled: 1, Done: 0 });
    expect(leaf(c, "11 worlds")).not.toBeNull(); // the header total is every world, not the filtered ones
    typeInto(search(c), "northline");
    expect(shown(c)).toEqual(["northline", "reply"]);
  });

  it("WEB_5_worlds_new_world_goes_home", async () => {
    const { c, app } = await renderWorlds();
    click(buttons(c, "New world")[0] as HTMLElement);
    expect(app.go).toHaveBeenCalledTimes(1);
    expect(app.go).toHaveBeenCalledWith("home");
  });
});

describe("WEB_5_worlds: status tabs and sizes", () => {
  it.each([
    ["All", ALL],
    ["Working", ["k1", "hires", "northline", "calls", "venues"]],
    ["Needs you", ["k1"]],
    ["Scheduled", ["invoice", "inbox", "pricing"]],
    ["Done", ["audit", "comp", "reply"]],
  ])("WEB_5_worlds_status_tabs_count_and_filter_%s", async (label, expected) => {
    const { c } = await renderWorlds();
    expect(statusTabs(c).map((t) => t.getAttribute("role"))).toEqual(Array(5).fill("tab"));
    expect(statusTabs(c).map((t) => t.tagName)).toEqual(Array(5).fill("BUTTON"));
    expect(tabCounts(c)).toEqual({ All: 11, Working: 5, "Needs you": 1, Scheduled: 3, Done: 3 });
    expect(Object.keys(tabCounts(c))).toEqual(TABS);
    click(tab(c, label));
    expect(statusTabs(c).map((t) => t.getAttribute("aria-selected"))).toEqual(
      TABS.map((l) => String(l === label)),
    );
    expect(shown(c)).toEqual(expected);
  });

  it("WEB_5_worlds_working_also_counts_a_world_that_needs_you_and_its_count_follows_decisions", async () => {
    const both = await renderWorlds({ dec: { depot: true, mail: true } });
    expect(tabCounts(both.c)).toEqual({
      All: 11,
      Working: 5,
      "Needs you": 0,
      Scheduled: 3,
      Done: 3,
    });
  });

  it.each([
    [
      "Cities",
      { All: 3, Working: 2, "Needs you": 1, Scheduled: 0, Done: 1 },
      ["k1", "hires", "audit"],
    ],
    [
      "Towns",
      { All: 4, Working: 1, "Needs you": 0, Scheduled: 3, Done: 0 },
      ["northline", "invoice", "inbox", "pricing"],
    ],
    [
      "Villages",
      { All: 4, Working: 2, "Needs you": 0, Scheduled: 0, Done: 2 },
      ["calls", "venues", "comp", "reply"],
    ],
  ])("WEB_5_worlds_size_%s_narrows_the_grid_and_tab_counts", async (label, counts, ids) => {
    const { c } = await renderWorlds();
    expect(qa(c, "button[aria-pressed]").map(text)).toEqual([
      "All sizes",
      "Cities",
      "Towns",
      "Villages",
    ]);
    expect(scaleButton(c, "All sizes").getAttribute("aria-pressed")).toBe("true");
    click(scaleButton(c, label));
    expect(qa(c, "button[aria-pressed]").map((b) => b.getAttribute("aria-pressed"))).toEqual(
      ["All sizes", "Cities", "Towns", "Villages"].map((l) => String(l === label)),
    );
    expect(tabCounts(c)).toEqual(counts);
    expect(shown(c)).toEqual(ids);
  });

  it("WEB_5_worlds_size_status_and_search_combine", async () => {
    const { c } = await renderWorlds();
    click(scaleButton(c, "Villages"));
    click(tab(c, "Done"));
    typeInto(search(c), "reply");
    expect(shown(c)).toEqual(["reply"]);
    expect(tabCounts(c)).toEqual({ All: 1, Working: 0, "Needs you": 0, Scheduled: 0, Done: 1 });
  });

  it("WEB_5_worlds_cards_sort_needs_then_working_then_scheduled_then_done_keeping_source_order", async () => {
    const api = worldsApi((d, a) => fx.worlds(d, a).reverse());
    const { c } = await renderWorlds({ api });
    expect(shown(c)).toEqual([
      "k1",
      "venues",
      "calls",
      "northline",
      "hires",
      "pricing",
      "inbox",
      "invoice",
      "reply",
      "comp",
      "audit",
    ]);
  });

  it("WEB_5_worlds_empty_state_names_the_filter", async () => {
    const BODY = "Try another filter, or start something new from Home.";
    const none = await renderWorlds({ dec: { depot: true, mail: true } });
    expect(text(none.c)).not.toContain(BODY);
    click(tab(none.c, "Needs you"));
    expect(leaf(none.c, "Nothing needs you right now")).not.toBeNull();
    expect(leaf(none.c, BODY)).not.toBeNull();
    expect(section(none.c, GRID)).toBeNull();
    click(tab(none.c, "All"));
    typeInto(search(none.c), "zzz");
    expect(leaf(none.c, "No worlds match")).not.toBeNull();
    expect(leaf(none.c, BODY)).not.toBeNull();
    expect(leaf(none.c, "Nothing needs you right now")).toBeNull();
  });
});

describe("WEB_5_worlds: cards", () => {
  it.each(["k1", "northline", "calls"])(
    "WEB_5_worlds_card_%s_is_a_link_that_opens_the_world_in_the_app",
    async (id) => {
      const { c, app } = await renderWorlds();
      const a = card(c, id);
      expect(a.tagName).toBe("A");
      expect(a.getAttribute("href")).toBe(hrefOf(id));
      const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
      act(() => {
        a.dispatchEvent(ev);
      });
      expect(ev.defaultPrevented).toBe(true);
      expect(app.go).toHaveBeenCalledTimes(1);
      expect(app.go).toHaveBeenCalledWith("world", { id });
    },
  );

  it.each<[string, (string | RegExp)[], string]>([
    [
      "k1",
      [
        "K1 electric scooter",
        "Concept to launch · Level 3 of 6 · Launch 14 Nov",
        "2 decisions",
        "46%",
        "City · 38 helpers",
        /£1,386\s*of £4,000/,
      ],
      "img",
    ],
    [
      "audit",
      [
        "Q3 audit prep",
        "Evidence pack signed off · Finished 12 Sep",
        "Done",
        "100%",
        /£2,140\s*of £2,500/,
      ],
      "img",
    ],
    [
      "northline",
      [
        "Supplier onboarding · Northline",
        "Contracts and portal access · Due Wed 30 Sep",
        "Working",
        "72%",
        "Town · 7 helpers",
        /£342\s*of £500/,
      ],
      "img",
    ],
    [
      "invoice",
      ["Weekly invoice match", "Next run Mon 09:00", "Scheduled", "—", /£0\.60\s*per run/],
      "img",
    ],
    [
      "calls",
      ["Summarise yesterday’s calls", "About 3 min left", "Working", "80%", "£0.40"],
      "img",
    ],
    ["comp", ["Competitor pricing", "Report · today 11:18", "Done", "Village · 1 helper"], "img"],
  ])("STUDIO_3_worlds_card_%s_copy_and_picture", async (id, wanted, art) => {
    const { c } = await renderWorlds();
    const t = text(card(c, id));
    for (const w of wanted) has(t, w);
    expect(card(c, id).querySelector(art), "the world's own picture").not.toBeNull();
  });

  it.each([
    { when: "none_decided", dec: {}, id: "k1", chip: "2 decisions" },
    { when: "depot_decided", dec: { depot: true }, id: "k1", chip: "1 decision" },
    { when: "both_decided", dec: { depot: true, mail: true }, id: "k1", chip: "Working" },
    { when: "none_decided", dec: {}, id: "invoice", chip: "Scheduled" },
    { when: "none_decided", dec: {}, id: "audit", chip: "Done" },
  ])("WEB_5_worlds_status_chip_says [$when] $id: $chip, with a dot", async ({ dec, id, chip }) => {
    const { c } = await renderWorlds({ dec });
    const el = leaf(card(c, id), chip);
    expect(el, chip).not.toBeNull();
    expect(el?.firstElementChild, "the status dot").not.toBeNull();
  });

  it("WEB_5_worlds_a_started_world_says_Starting_and_comes_first_among_working", async () => {
    const added: World[] = [
      fx.makeWorld("quick", "Compare three suppliers", 1),
      fx.makeWorld("workspace", "Plan the offsite", 2),
    ];
    const { c } = await renderWorlds({ added });
    expect(leaf(c, "13 worlds")).not.toBeNull();
    expect(shown(c).slice(0, 3)).toEqual(["k1", "new1", "new2"]); // needs first, then working in source order
    expect(leaf(card(c, "new1"), "Starting")).not.toBeNull();
    expect(text(card(c, "new1"))).toContain("Starting now");
    const t = text(card(c, "new2"));
    expect(t).toMatch(/Starting/);
    expect(t).toMatch(/£0\.00\s*of £400/);
    expect(t).toContain("4%");
  });

  const widths = (el: Element) =>
    qa(el, "*").flatMap((e) =>
      e.tagName === "IMG"
        ? []
        : (/(?:^|[;\s])width:\s*(\d+)%/.exec(e.getAttribute("style") ?? "")?.[1] ?? []),
    );

  it("WEB_5_worlds_progress_bar_width_and_label_follow_prog", async () => {
    const { c } = await renderWorlds();
    expect(widths(card(c, "k1"))).toEqual(["46"]);
    expect(widths(card(c, "northline"))).toEqual(["72"]);
    expect(widths(card(c, "invoice")), "no progress served: an empty bar").toEqual(["0"]);
    expect(widths(card(c, "calls"))).toEqual(["80"]);
  });

  it("WEB_5_worlds_a_city_without_progress_shows_an_em_dash", async () => {
    const api = worldsApi((d, a) =>
      fx.worlds(d, a).map((w) => {
        if (w.id !== "k1") return w;
        const { prog: _drop, ...rest } = w;
        return rest;
      }),
    );
    const { c } = await renderWorlds({ api });
    expect(text(card(c, "k1"))).toContain("—");
    expect(text(card(c, "k1"))).not.toMatch(/\d+%/);
  });
});

describe("WEB_5_worlds: waiting for you and all caught up", () => {
  it("WEB_5_worlds_spotlight_shows_k1_the_count_and_one_card_per_decision", async () => {
    const { c, app } = await renderWorlds();
    const s = spotlight(c);
    for (const t of [
      "K1 electric scooter",
      "2 buildings paused",
      "Laptop Depot · budget sign-off",
      "6 test laptops for firmware, £3,420. Above the £2,500 district limit.",
      "Mail Room gate · supplier brief",
      "Brief ready for 3 battery suppliers outside the company. Nothing sent yet.",
    ])
      expect(leaf(s, t), t).not.toBeNull();
    expect(text(s).indexOf("Laptop Depot")).toBeLessThan(text(s).indexOf("Mail Room gate"));
    expect(s.querySelector("svg"), "the agent figure").not.toBeNull();
    expect(buttons(s, "Open in world")).toHaveLength(2);
    expect(text(c)).not.toContain("You’re all caught up");
    click(buttons(s, "Approve £3,420")[0] as HTMLElement);
    expect(app.decide).toHaveBeenLastCalledWith("depot");
    click(buttons(s, "Send brief")[0] as HTMLElement);
    expect(app.decide).toHaveBeenLastCalledWith("mail");
    expect(app.decide).toHaveBeenCalledTimes(2);
    click(buttons(s, "Open in world")[1] as HTMLElement);
    expect(app.go).toHaveBeenCalledWith("world", { id: "k1" });
  });

  it("WEB_5_worlds_spotlight_stays_when_the_filters_hide_k1", async () => {
    const { c } = await renderWorlds();
    typeInto(search(c), "zzz");
    expect(leaf(c, "WAITING FOR YOU")).not.toBeNull();
  });

  it("WEB_5_worlds_a_decided_card_shows_its_done_text_with_a_check_and_the_count_drops", async () => {
    const r = await renderWorlds({ dec: { depot: true } });
    const s = spotlight(r.c);
    expect(leaf(s, "1 building paused")).not.toBeNull();
    expect(buttons(s, "Approve £3,420")).toHaveLength(0);
    expect(buttons(s, "Send brief")).toHaveLength(1);
    expect(buttons(s, "Open in world")).toHaveLength(1);
    const done = leaf(s, "Approved · just now");
    expect(done, "the done text").not.toBeNull();
    expect((done?.parentElement ?? s).querySelector("svg"), "a check mark").not.toBeNull();
    expect(leaf(s, "Sent to 3 suppliers · just now")).toBeNull();
    expect(leaf(card(r.c, "k1"), "1 decision")).not.toBeNull();
    await r.update({ dec: { depot: true, mail: true } });
    expect(leaf(r.c, "WAITING FOR YOU")).toBeNull();
    expect(leaf(card(r.c, "k1"), "Working")).not.toBeNull();
  });

  it("WEB_5_worlds_when_nothing_is_left_the_all_caught_up_banner_replaces_the_spotlight", async () => {
    const { c } = await renderWorlds({ dec: { depot: true, mail: true } });
    expect(leaf(c, "You’re all caught up")).not.toBeNull();
    expect(
      leaf(c, "K1 electric scooter is moving again. Tilo will ask if anything else needs you."),
    ).not.toBeNull();
    for (const gone of [
      "WAITING FOR YOU",
      "Open in world",
      "Approved · just now",
      "buildings paused",
    ]) {
      expect(text(c), gone).not.toContain(gone);
    }
  });
});

describe("WEB_5_worlds: invariants over any sequence of filter changes", () => {
  it("WEB_5_worlds_property_the_selected_count_equals_the_cards_shown", async () => {
    const { c } = await renderWorlds();
    const op = fc.oneof(
      fc.constantFrom(...TABS).map((l) => () => click(tab(c, l))),
      fc
        .constantFrom("All sizes", "Cities", "Towns", "Villages")
        .map((l) => () => click(scaleButton(c, l))),
      fc.constantFrom("", "northline", "O", "zzz", "q3").map((s) => () => typeInto(search(c), s)),
    );
    fc.assert(
      fc.property(fc.array(op, { minLength: 1, maxLength: 8 }), (ops) => {
        for (const o of ops) o();
        const ids = shown(c);
        const on = statusTabs(c).filter((t) => t.getAttribute("aria-selected") === "true");
        expect(on).toHaveLength(1);
        expect(tabCounts(c)[text(on[0] ?? null).replace(/\d+$/, "")]).toBe(ids.length);
        expect(new Set(ids).size).toBe(ids.length);
        expect(section(c, GRID) !== null).toBe(ids.length > 0);
        expect(text(c).includes("Try another filter, or start something new from Home.")).toBe(
          ids.length === 0,
        );
        expect(leaf(c, "11 worlds")).not.toBeNull();
      }),
      { numRuns: 30 },
    );
  });
});
