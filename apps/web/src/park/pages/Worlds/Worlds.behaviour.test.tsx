import fc from "fast-check";
// @vitest-environment happy-dom
// WEB-5 acceptance: the Park "Worlds" page (design_handoff_tilo_web_app/design/Tilo App Worlds.dc.html, its
// renderVals(); inventory.md "Tilo App Worlds.dc.html"; README "Worlds"; plan sections 8c and 10).
// Pinned surface: pages/Worlds/WorldsPage.tsx exports `WorldsPage({ app }: { app: AppCtx })`, pages/Worlds/index.ts
// default-exports it; the root carries data-testid="park-page-worlds" (the shell's own page test ids); data comes
// only from useParkApi().getWorlds(app.dec, app.added) and getDecisions(); navigation only app.go; approval only
// app.decide. Defaults taken where the reference is silent are listed in the WEB-5 test report.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  buttons,
  card,
  cardIds,
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

const SUBTITLE = "Every job Tilo is running, sized by scale: cities, towns and villages.";
const SEC = ["Cities", "Towns", "Villages"] as const;
const ALL = {
  Cities: ["k1", "hires", "audit"],
  Towns: ["northline", "invoice", "inbox", "pricing"],
  Villages: ["calls", "venues", "comp", "reply"],
};
const sections = (c: HTMLElement) => Object.fromEntries(SEC.map((s) => [s, cardIds(c, s)]));
const text = (el: Element | null) => el?.textContent ?? "";
/** Asserts `t` holds the string, or matches the pattern. */
const has = (t: string, w: string | RegExp) =>
  typeof w === "string" ? expect(t).toContain(w) : expect(t).toMatch(w);

describe("WEB_5_worlds: header, search and New world", () => {
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
    expect(text(c)).toContain("Not connected yet");
    expect(qa(c, "a[href]")).toHaveLength(0);
    expect(text(q(c, "h1"))).toBe("Worlds");
  });

  it("WEB_5_worlds_search_is_named_and_filters_by_name_ignoring_case", async () => {
    const { c } = await renderWorlds();
    expect(search(c).placeholder).toBe("Search worlds");
    typeInto(search(c), "INVOICE");
    expect(search(c).value).toBe("INVOICE");
    expect(sections(c)).toEqual({ Cities: [], Towns: ["invoice"], Villages: [] });
    expect(section(c, "Cities")).toBeNull();
    expect(tabCounts(c)).toEqual({ All: 1, "Needs you": 0, Running: 0, Scheduled: 1, Ready: 0 });
    expect(leaf(c, "11 worlds")).not.toBeNull(); // the header total is every world, not the filtered ones
    typeInto(search(c), "northline");
    expect(sections(c)).toEqual({ Cities: [], Towns: ["northline"], Villages: ["reply"] });
  });

  it("WEB_5_worlds_new_world_goes_home", async () => {
    const { c, app } = await renderWorlds();
    click(buttons(c, "New world")[0] as HTMLElement);
    expect(app.go).toHaveBeenCalledTimes(1);
    expect(app.go).toHaveBeenCalledWith("home");
  });
});

describe("WEB_5_worlds: status tabs and scale legend", () => {
  it.each([
    ["All", ALL],
    ["Needs you", { Cities: ["k1"], Towns: [], Villages: [] }],
    ["Running", { Cities: ["k1", "hires"], Towns: ["northline"], Villages: ["calls", "venues"] }],
    ["Scheduled", { Cities: [], Towns: ["invoice", "inbox", "pricing"], Villages: [] }],
    ["Ready", { Cities: ["audit"], Towns: [], Villages: ["comp", "reply"] }],
  ])("WEB_5_worlds_status_tabs_count_and_filter_%s", async (label, expected) => {
    const { c } = await renderWorlds();
    expect(statusTabs(c).map((t) => t.getAttribute("role"))).toEqual(Array(5).fill("tab"));
    expect(statusTabs(c).map((t) => t.tagName)).toEqual(Array(5).fill("BUTTON"));
    expect(tabCounts(c)).toEqual({ All: 11, "Needs you": 1, Running: 5, Scheduled: 3, Ready: 3 });
    expect(Object.keys(tabCounts(c))).toEqual([
      "All",
      "Needs you",
      "Running",
      "Scheduled",
      "Ready",
    ]);
    click(tab(c, label));
    expect(statusTabs(c).map((t) => t.getAttribute("aria-selected"))).toEqual(
      ["All", "Needs you", "Running", "Scheduled", "Ready"].map((l) => String(l === label)),
    );
    expect(sections(c)).toEqual(expected);
  });

  it("WEB_5_worlds_running_also_counts_a_world_that_needs_you_and_its_count_follows_decisions", async () => {
    const both = await renderWorlds({ dec: { depot: true, mail: true } });
    expect(tabCounts(both.c)).toEqual({
      All: 11,
      "Needs you": 0,
      Running: 5,
      Scheduled: 3,
      Ready: 3,
    });
  });

  it.each([
    ["Cities", { All: 3, "Needs you": 1, Running: 2, Scheduled: 0, Ready: 1 }],
    ["Towns", { All: 4, "Needs you": 0, Running: 1, Scheduled: 3, Ready: 0 }],
    ["Villages", { All: 4, "Needs you": 0, Running: 2, Scheduled: 0, Ready: 2 }],
  ])("WEB_5_worlds_scale_legend_%s_narrows_sections_and_tab_counts", async (label, counts) => {
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
    expect(SEC.filter((s) => section(c, s))).toEqual([label]);
    expect(leaf(c, "SCALE")).not.toBeNull();
  });

  it("WEB_5_worlds_scale_status_and_search_combine", async () => {
    const { c } = await renderWorlds();
    click(scaleButton(c, "Villages"));
    click(tab(c, "Ready"));
    typeInto(search(c), "reply");
    expect(sections(c)).toEqual({ Cities: [], Towns: [], Villages: ["reply"] });
    expect(tabCounts(c)).toEqual({ All: 1, "Needs you": 0, Running: 0, Scheduled: 0, Ready: 1 });
  });

  it("WEB_5_worlds_sections_title_count_and_blurb", async () => {
    const { c } = await renderWorlds();
    const blurb = {
      Cities: "3 · big projects with districts and gates",
      Towns: "4 · routines and small projects",
      Villages: "4 · quick tasks, done in minutes",
    };
    for (const s of SEC) {
      expect(leaf(section(c, s) as HTMLElement, s), s).not.toBeNull();
      expect(leaf(section(c, s) as HTMLElement, blurb[s]), s).not.toBeNull();
    }
    click(tab(c, "Running"));
    expect(
      leaf(section(c, "Cities") as HTMLElement, "2 · big projects with districts and gates"),
    ).not.toBeNull();
    expect(
      leaf(section(c, "Villages") as HTMLElement, "2 · quick tasks, done in minutes"),
    ).not.toBeNull();
  });

  it("WEB_5_worlds_cards_sort_needs_then_running_then_scheduled_then_ready_keeping_source_order", async () => {
    const api = worldsApi((d, a) => fx.worlds(d, a).reverse());
    const { c } = await renderWorlds({ api });
    expect(sections(c)).toEqual({
      Cities: ["k1", "hires", "audit"],
      Towns: ["northline", "pricing", "inbox", "invoice"],
      Villages: ["venues", "calls", "reply", "comp"],
    });
  });

  it("WEB_5_worlds_empty_state_names_the_filter", async () => {
    const BODY = "Try another filter, or start something new from Home.";
    const none = await renderWorlds({ dec: { depot: true, mail: true } });
    expect(text(none.c)).not.toContain(BODY);
    click(tab(none.c, "Needs you"));
    expect(leaf(none.c, "Nothing needs you right now")).not.toBeNull();
    expect(leaf(none.c, BODY)).not.toBeNull();
    expect(qa(none.c, "section[aria-label]")).toHaveLength(0);
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

  it.each<[string, (string | RegExp)[]]>([
    [
      "k1",
      [
        "WORKSPACE",
        "K1 electric scooter",
        "Concept to launch · Level 3 of 6",
        "2 decisions",
        "46%",
        "Spend",
        /£1,386\s*of £4,000/,
        "Agents",
        "38",
        "Launch",
        "14 Nov",
      ],
    ],
    [
      "hires",
      [
        "WORKSPACE",
        "Onboard 12 new hires",
        "Accounts, HR and training",
        "Running",
        "58%",
        /£228\s*of £600/,
        "14",
        "Due",
        "Fri 2 Oct",
      ],
    ],
    [
      "audit",
      [
        "Q3 audit prep",
        "Evidence pack signed off",
        "Ready",
        "100%",
        /£2,140\s*of £2,500/,
        "22",
        "Finished",
        "12 Sep",
      ],
    ],
  ])("WEB_5_worlds_city_card_%s_copy", async (id, wanted) => {
    const { c } = await renderWorlds();
    const t = text(card(c, id));
    for (const w of wanted) has(t, w);
    expect(card(c, id).querySelector("svg"), "a mini world map").not.toBeNull();
  });

  it.each<[string, (string | RegExp)[], string[]]>([
    [
      "northline",
      [
        "WORKSPACE",
        "Supplier onboarding · Northline",
        "Contracts and portal access",
        "Running",
        "Due Wed 30 Sep",
        /£342\s*of £500/,
      ],
      ["Spend", "Agents"],
    ],
    [
      "invoice",
      [
        "ROUTINE",
        "Weekly invoice match",
        "Last run 142 matched, 3 flagged",
        "Scheduled",
        "Next run Mon 09:00",
        /£0\.60\s*per run/,
      ],
      ["Spend", "%"],
    ],
  ])("WEB_5_worlds_town_card_%s_copy_and_strip", async (id, wanted, absent) => {
    const { c } = await renderWorlds();
    const t = text(card(c, id));
    for (const w of wanted) has(t, w);
    for (const a of absent) expect(t).not.toContain(a);
    expect(card(c, id).querySelector("svg"), "a building strip").not.toBeNull();
  });

  it.each<[string, string[]]>([
    ["calls", ["Running", "Summarise yesterday’s calls", "About 3 min left"]],
    ["comp", ["Ready", "Competitor pricing", "Report · today 11:18"]],
  ])("WEB_5_worlds_village_card_%s_copy_and_single_building", async (id, wanted) => {
    const { c } = await renderWorlds();
    const t = text(card(c, id));
    for (const w of wanted) expect(t).toContain(w);
    for (const hidden of ["QUICK TASK", "Spend", "Agents", "%"])
      expect(t, hidden).not.toContain(hidden);
    expect(card(c, id).querySelector("svg")).not.toBeNull();
  });

  it.each([
    { when: "none_decided", dec: {}, id: "k1", chip: "2 decisions" },
    { when: "depot_decided", dec: { depot: true }, id: "k1", chip: "1 decision" },
    { when: "both_decided", dec: { depot: true, mail: true }, id: "k1", chip: "Running" },
    { when: "none_decided", dec: {}, id: "invoice", chip: "Scheduled" },
    { when: "none_decided", dec: {}, id: "audit", chip: "Ready" },
  ])("WEB_5_worlds_status_chip_says [$when] $id: $chip, with a dot", async ({ dec, id, chip }) => {
    const { c } = await renderWorlds({ dec });
    const el = leaf(card(c, id), chip);
    expect(el, chip).not.toBeNull();
    expect(el?.firstElementChild, "the status dot").not.toBeNull();
  });

  it("WEB_5_worlds_a_started_world_says_Starting_and_comes_first_in_its_section", async () => {
    const added: World[] = [
      fx.makeWorld("quick", "Compare three suppliers", 1),
      fx.makeWorld("workspace", "Plan the offsite", 2),
    ];
    const { c } = await renderWorlds({ added });
    expect(leaf(c, "13 worlds")).not.toBeNull();
    expect(cardIds(c, "Villages")[0]).toBe("new1");
    expect(cardIds(c, "Cities").slice(0, 2)).toEqual(["k1", "new2"]); // needs first, then running in source order
    expect(leaf(card(c, "new1"), "Starting")).not.toBeNull();
    expect(text(card(c, "new1"))).toContain("Starting now");
    const t = text(card(c, "new2"));
    expect(t).toMatch(/Starting/);
    expect(t).toMatch(/£0\.00\s*of £400/);
    expect(t).toContain("4%");
  });

  const widths = (el: Element) =>
    qa(el, "*").flatMap(
      (e) => /(?:^|[;\s])width:\s*(\d+)%/.exec(e.getAttribute("style") ?? "")?.[1] ?? [],
    );

  it("WEB_5_worlds_progress_bar_width_and_label_follow_prog", async () => {
    const { c } = await renderWorlds();
    expect(widths(card(c, "k1"))).toEqual(["46"]);
    expect(widths(card(c, "northline"))).toEqual(["72"]); // a town draws the bar only when prog is set
    expect(widths(card(c, "invoice"))).toEqual([]);
    expect(widths(card(c, "calls")), "a village has no bar").toEqual([]);
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
    expect(leaf(card(r.c, "k1"), "Running")).not.toBeNull();
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
      fc
        .constantFrom("All", "Needs you", "Running", "Scheduled", "Ready")
        .map((l) => () => click(tab(c, l))),
      fc
        .constantFrom("All sizes", "Cities", "Towns", "Villages")
        .map((l) => () => click(scaleButton(c, l))),
      fc.constantFrom("", "northline", "O", "zzz", "q3").map((s) => () => typeInto(search(c), s)),
    );
    fc.assert(
      fc.property(fc.array(op, { minLength: 1, maxLength: 8 }), (ops) => {
        for (const o of ops) o();
        const shown = SEC.flatMap((s) => cardIds(c, s));
        const on = statusTabs(c).filter((t) => t.getAttribute("aria-selected") === "true");
        expect(on).toHaveLength(1);
        expect(tabCounts(c)[text(on[0] ?? null).replace(/\d+$/, "")]).toBe(shown.length);
        expect(new Set(shown).size).toBe(shown.length);
        for (const s of SEC) {
          const n = cardIds(c, s).length;
          expect(section(c, s) !== null, s).toBe(n > 0);
          if (n > 0) expect(text(section(c, s)), s).toMatch(new RegExp(`${s}\\s*${n} · `));
        }
        expect(text(c).includes("Try another filter, or start something new from Home.")).toBe(
          shown.length === 0,
        );
        expect(leaf(c, "11 worlds")).not.toBeNull();
      }),
      { numRuns: 30 },
    );
  });
});
