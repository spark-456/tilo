// @vitest-environment happy-dom
// WEB-6 acceptance: what the World page shows. Pinned to the user's design, not to an implementation:
//   design_handoff_tilo_web_app/design/Tilo App World.dc.html (the reference page; its data is tilo-app.js),
//   README "World detail" and inventory.md "Tilo App World.dc.html" (regions and static copy),
//   docs/web-app-rebuild-plan.md sections 8a and 10.
// Pinned module surface: src/park/pages/World/WorldPage.tsx exports `WorldPage({ app }: { app: AppCtx })`
// (named export, no default); it renders inside ParkProvider (data through useParkApi), draws the sheet
// itself (`section.park-sheet`) and no <main> (the shell owns it); the world is `app.params.id`.
// Reference behaviours kept on purpose: "agents" is always plural in a district's count; a Town's spend note
// reads "Each run costs about <spend>" even for a project with a budget; the fixtures are K1 (City), the
// "hires" City, four Towns and six Villages, and the test names the design's own strings for them.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  ALL,
  CALLS,
  COMP,
  DECISIONS,
  HIRES,
  INVOICE,
  INVOICE_RUNS,
  K1,
  K1_ACTIVITY,
  K1_ACTIVITY_DEPOT,
  K1_ACTIVITY_MAIL,
  NORTHLINE,
  NORTHLINE_RUNS,
  NO_RUNS,
  NO_SKILLS,
  OUT,
  VENUES,
  type WorldCopy,
  k1Districts,
} from "../../../../test-support/park/worldCopy";
import {
  ART,
  NIGHT,
  breadcrumb,
  climb,
  controlFlat,
  controls,
  elWithFlat,
  elWithText,
  flat,
  hasControl,
  mapBlock,
  mountWorld,
  pageText,
  progressBeside,
  progressOf,
  region,
  rowOf,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { makeWorld } from "../../api/fixtures";

afterEach(cleanup);

const chipFor = (c: WorldCopy): string => (c.id === "k1" ? "2 decisions" : c.chip);

describe("WEB_6_world_render: the page frame", () => {
  it("WEB_6_world_render_the_root_carries_the_registry_testid_park_page_world", async () => {
    const { el } = await mountWorld();
    expect(qa(el, '[data-testid="park-page-world"]')).toHaveLength(1);
  });

  it("WEB_6_world_render_one_h1_that_is_the_world_name_in_a_sheet_and_no_main", async () => {
    const { el } = await mountWorld();
    expect(qa(el, "main")).toHaveLength(0); // the landmark belongs to the shell
    const h1s = qa(el, "h1");
    expect(h1s).toHaveLength(1);
    expect(textOf(q(el, "h1"))).toBe(K1.name);
    expect(q(el, "section.park-sheet").contains(q(el, "h1"))).toBe(true);
  });

  it("WEB_6_world_render_the_h1_can_take_focus_from_the_shell_after_a_route_change", async () => {
    const { el } = await mountWorld();
    expect(q(el, "h1").getAttribute("tabindex")).toBe("-1"); // as the Skills and Team headings
  });

  it("WEB_6_world_render_no_sample_data_chip_in_the_page_the_shell_owns_it", async () => {
    const { el } = await mountWorld();
    expect(pageText(el)).not.toMatch(/sample data/i);
  });

  it("WEB_6_world_render_the_labelled_regions_are_Breadcrumb_the_main_section_and_Activity", async () => {
    // inventory.md: "Labelled regions: Breadcrumb · Activity"; the reference's first section is labelled by mainT.
    const { el } = await mountWorld();
    expect(breadcrumb(el).tagName).toBe("NAV");
    expect(region(el, "Districts").tagName).toBe("SECTION");
    expect(region(el, "Activity").tagName).toBe("SECTION");
    cleanup();
    const town = await mountWorld({ id: "northline" });
    expect(region(town.el, "Run history").tagName).toBe("SECTION");
    cleanup();
    const village = await mountWorld({ id: "calls" });
    expect(region(village.el, "Result").tagName).toBe("SECTION");
  });
});

describe("WEB_6_world_render: breadcrumb", () => {
  // STUDIO-3 ("Tilo S World.dc.html"): the breadcrumb is one back link, "← All worlds"; the name is the h1 below it.
  it("STUDIO_3_world_render_breadcrumb_reads_All_worlds_with_a_real_link_to_Worlds", async () => {
    const { el } = await mountWorld();
    const nav = breadcrumb(el);
    expect(flat(textOf(nav))).toBe(flat("All worlds"));
    const link = controlFlat(nav, "All worlds");
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBeTruthy();
    expect(link.querySelector("svg"), "the back arrow of the reference").not.toBeNull();
    expect(controls(nav)).toHaveLength(1); // the current page is text, not a link
  });
});

describe("WEB_6_world_render: header (eyebrow, status chip, name, meta)", () => {
  it.each(ALL.map((c) => [c.id, c] as const))("WEB_6_world_render_header_of_%s", async (_id, c) => {
    const { el } = await mountWorld({ id: c.id });
    expect(textOf(q(el, "h1"))).toBe(c.name);
    expect(elWithText(el, c.eyebrow), `eyebrow ${c.eyebrow}`).toBeTruthy();
    expect(elWithText(el, chipFor(c)), `status chip ${chipFor(c)}`).toBeTruthy();
    expect(elWithText(el, c.meta), "meta line").toBeTruthy();
  });

  it("WEB_6_world_render_the_chip_has_a_dot_and_the_text_says_the_state_not_colour_alone", async () => {
    const { el } = await mountWorld({ id: "invoice" });
    const chip = elWithText(el, "Scheduled");
    const host = chip?.querySelector("span") ? chip : chip?.parentElement;
    expect(host?.querySelector("span"), "the 7px state dot").not.toBeNull();
  });

  it("WEB_6_world_render_one_agent_is_singular_in_the_meta_line", async () => {
    const { el } = await mountWorld({ id: "calls" });
    expect(elWithText(el, CALLS.meta)).toBeTruthy();
    expect(pageText(el)).not.toContain("1 agents ·"); // the meta line
  });

  it("WEB_6_world_render_needs_you_world_shows_the_decision_count_from_app_needsLeft", async () => {
    const both = await mountWorld({ dec: {} });
    expect(elWithText(both.el, "2 decisions")).toBeTruthy();
    cleanup();
    const one = await mountWorld({ dec: { depot: true } });
    expect(elWithText(one.el, "1 decision")).toBeTruthy();
    expect(elWithText(one.el, "2 decisions")).toBeUndefined();
    cleanup();
    const none = await mountWorld({ dec: { depot: true, mail: true } });
    expect(
      elWithText(none.el, "Working"),
      "no decision is open: the world is running",
    ).toBeTruthy();
    expect(pageText(none.el)).not.toMatch(/\d decisions?\b/);
  });

  it("WEB_6_world_render_a_finished_world_says_Done", async () => {
    const { el } = await mountWorld({ id: "audit" });
    expect(elWithText(el, "Done")).toBeTruthy();
    expect(elWithText(el, "CITY · WORKSPACE")).toBeTruthy();
  });

  it("WEB_6_world_render_a_new_world_says_Starting_with_its_own_tier_and_numbers", async () => {
    const added = [makeWorld("quick", "Compare three suppliers", 1)];
    const { el } = await mountWorld({ id: "new1", added });
    expect(textOf(q(el, "h1"))).toBe("Compare three suppliers");
    expect(elWithText(el, "VILLAGE · QUICK TASK")).toBeTruthy();
    expect(elWithText(el, "Starting"), "chip").toBeTruthy();
    expect(elWithText(el, "Owned by Alex Morgan · started Just now · 2 agents")).toBeTruthy();
    expect(elWithText(el, "Quick task · 2 agents"), "hero tag").toBeTruthy();
    expect(elWithText(el, "4%"), "progress label").toBeTruthy();
    expect(elWithText(el, "£0.00")).toBeTruthy();
    expect(
      elWithText(el, "Working on it. You’ll get a notification when it’s ready."),
    ).toBeTruthy();
    expect(elWithText(el, "Starting now"), "the running line").toBeTruthy();
  });

  it("WEB_6_world_render_a_new_routine_has_no_runs_yet", async () => {
    const added = [makeWorld("routine", "Every Monday, match invoices to purchase orders", 1)];
    const { el } = await mountWorld({ id: "new1", added });
    expect(elWithText(el, "TOWN · ROUTINE")).toBeTruthy();
    expect(elWithText(el, "Starting")).toBeTruthy();
    const runs = region(el, "Run history");
    expect(textOf(runs)).toContain(NO_RUNS);
    expect(elWithText(runs, "0 recent runs")).toBeTruthy();
    expect(hasControl(runs, "Run now")).toBe(true);
  });
});

describe("WEB_6_world_render: the map card (art, hero tag, progress, legend)", () => {
  it("WEB_6_world_render_city_map_holds_the_art_the_hero_tag_and_the_legend", async () => {
    const { el } = await mountWorld();
    const map = mapBlock(el, K1.heroTag);
    expect(map.querySelectorAll(ART).length).toBeGreaterThanOrEqual(1);
    const legend = elWithFlat(el, "Building Needs you Done Planned");
    expect(legend, "the four legend items in the reference order").toBeTruthy();
    expect(legend?.children).toHaveLength(4);
    // STUDIO-3 ("Tilo S World.dc.html"): the legend is a card on the city, at its bottom left.
    expect(map.contains(legend ?? null), "the legend sits on the city").toBe(true);
  });

  it("WEB_6_world_render_the_second_city_art_is_its_own_plan", async () => {
    const k1 = await mountWorld();
    const k1Art = mapBlock(k1.el, K1.heroTag).querySelector(ART)?.outerHTML;
    cleanup();
    const hires = await mountWorld({ id: "hires" });
    const hiresArt = mapBlock(hires.el, HIRES.heroTag).querySelector(ART)?.outerHTML;
    expect(k1Art).toBeTruthy();
    expect(hiresArt).toBeTruthy();
    expect(hiresArt).not.toBe(k1Art);
  });

  it("WEB_6_world_render_the_city_art_follows_the_decisions_and_the_time_of_day", async () => {
    const day = await mountWorld();
    const dayArt = mapBlock(day.el, K1.heroTag).querySelector(ART)?.outerHTML;
    await day.setDec({ depot: true, mail: true });
    const decidedArt = mapBlock(day.el, K1.heroTag).querySelector(ART)?.outerHTML;
    expect(decidedArt, "the Laptop Depot and Mail Room buildings leave 'needs'").not.toBe(dayArt);
    cleanup();
    const night = await mountWorld({ app: NIGHT });
    const nightArt = mapBlock(night.el, K1.heroTag).querySelector(ART)?.outerHTML;
    expect(nightArt).not.toBe(dayArt);
  });

  it("WEB_6_world_render_a_town_shows_its_row_of_buildings_and_no_legend", async () => {
    const { el } = await mountWorld({ id: "northline" });
    const map = mapBlock(el, NORTHLINE.heroTag);
    expect(map.querySelectorAll(ART).length, "two buildings in a row").toBeGreaterThanOrEqual(2);
    expect(elWithFlat(el, "Building Needs you Done Planned")).toBeUndefined();
  });

  it("WEB_6_world_render_a_village_shows_its_single_building_and_no_legend", async () => {
    const { el } = await mountWorld({ id: "calls" });
    const map = mapBlock(el, CALLS.heroTag);
    expect(map.querySelectorAll(ART).length).toBeGreaterThanOrEqual(1);
    expect(elWithFlat(el, "Building Needs you Done Planned")).toBeUndefined();
  });

  it.each(ALL.map((c) => [c.id, c] as const))(
    "WEB_6_world_render_hero_tag_and_progress_of_%s",
    async (_id, c) => {
      const { el } = await mountWorld({ id: c.id });
      expect(elWithText(el, c.heroTag), `hero tag ${c.heroTag}`).toBeTruthy();
      const label = elWithText(el, c.progress);
      expect(label, `progress label ${c.progress}`).toBeTruthy();
      expect(progressBeside(label as HTMLElement), "bar width").toBeCloseTo(c.progW, 1);
    },
  );

  it("WEB_6_world_render_a_world_without_a_progress_value_shows_its_next_value_and_an_empty_bar", async () => {
    const { el } = await mountWorld({ id: "invoice" });
    const label = elWithText(el, "Mon 09:00");
    expect(label).toBeTruthy();
    expect(progressBeside(label as HTMLElement)).toBe(0);
  });

  it("WEB_6_world_render_no_overlay_while_the_world_is_not_paused", async () => {
    const { el } = await mountWorld();
    expect(pageText(el)).not.toContain("Paused · agents are waiting");
  });
});

describe("WEB_6_world_render: the Spend card", () => {
  it.each(ALL.map((c) => [c.id, c] as const))(
    "WEB_6_world_render_spend_card_of_%s",
    async (_id, c) => {
      const { el } = await mountWorld({ id: c.id });
      const title = elWithText(el, "Spend");
      expect(title, "the card title").toBeTruthy();
      const card = climb(
        title,
        (n) => textOf(n).includes("Ledger") && textOf(n).includes(c.spendNote),
      );
      expect(flat(textOf(card))).toBe(flat(`Spend Ledger ${c.spend} ${c.of} ${c.spendNote}`));
      const w = progressOf(card);
      if (c.spendW === null) expect(w, "no budget, no bar").toBeNull();
      else expect(w).toBeCloseTo(c.spendW, 0);
    },
  );

  it("WEB_6_world_render_the_spend_bar_never_passes_100_percent", async () => {
    // Reference: sp = Math.min(100, spendV / budget * 100). A world over budget fills the bar and stops.
    const base = (await import("../../api/fixtureApi")).createFixtureApi();
    const over = {
      ...base,
      getWorlds: async (...a: Parameters<typeof base.getWorlds>) => {
        const r = await base.getWorlds(...a);
        return {
          ...r,
          data: r.data.map((w) => (w.id === "hires" ? { ...w, spendV: 900, spend: "£900" } : w)),
        };
      },
    };
    const { el } = await mountWorld({ id: "hires", api: over });
    const card = climb(
      elWithText(el, "Spend"),
      (n) => textOf(n).includes("Ledger") && textOf(n).includes("£900"),
    );
    expect(progressOf(card)).toBe(100);
  });
});

describe("WEB_6_world_render: facts, skills and tools", () => {
  it.each(ALL.map((c) => [c.id, c] as const))(
    "WEB_6_world_render_facts_skills_and_tools_of_%s",
    async (_id, c) => {
      const { el } = await mountWorld({ id: c.id });
      const owner = elWithText(el, "Owner");
      expect(owner, "the first fact label").toBeTruthy();
      const card = climb(owner, (n) => textOf(n).includes("Tools"));
      const facts = c.facts.map(([k, v]) => `${k} ${v}`).join(" ");
      const skills = c.skills.length > 0 ? c.skills.join(" ") : NO_SKILLS;
      const tools = c.tools.map(([m, n]) => `${m}${n}`).join(" ");
      expect(flat(textOf(card))).toBe(flat(`${facts} Skills ${skills} Tools ${tools}`));
      for (const s of c.skills) expect(hasControl(card, s), `skill chip ${s}`).toBe(true);
      for (const [m, n] of c.tools) expect(controlFlat(card, `${m}${n}`)).toBeTruthy();
      if (c.skills.length === 0) expect(hasControl(card, NO_SKILLS)).toBe(false); // plain text
    },
  );
});

describe("WEB_6_world_render: Districts (City)", () => {
  it.each([[{}], [{ depot: true }], [{ mail: true }], [{ depot: true, mail: true }]] as const)(
    "WEB_6_world_render_K1_districts_for_decisions_%o",
    async (dec) => {
      const { el } = await mountWorld({ dec });
      const section = region(el, "Districts");
      expect(textOf(q(section, "h2"))).toBe("Districts");
      expect(elWithText(section, "5 districts")).toBeTruthy();
      let last = -1;
      for (const d of k1Districts(dec)) {
        const row = rowOf(section, d.name, d.count);
        expect(flat(textOf(row)), d.name).toBe(flat(`${d.name} ${d.note} ${d.count} ${d.chip}`));
        expect(progressOf(row), `${d.name} bar`).toBe(d.w);
        expect(row.querySelector("svg"), `${d.name} icon`).not.toBeNull();
        const at = textOf(section).indexOf(d.name);
        expect(at, `${d.name} keeps the reference order`).toBeGreaterThan(last);
        last = at;
      }
    },
  );

  it("WEB_6_world_render_the_second_city_lists_its_four_districts", async () => {
    const { el } = await mountWorld({ id: "hires" });
    const section = region(el, "Districts");
    expect(elWithText(section, "4 districts")).toBeTruthy();
    const training = rowOf(section, "Training", "0 of 1 buildings · 3 agents");
    expect(flat(textOf(training))).toBe(
      flat("Training Course plan being built 0 of 1 buildings · 3 agents Building"),
    );
    expect(progressOf(training)).toBe(0);
    const accounts = rowOf(section, "Accounts", "2 of 2 buildings · 5 agents");
    expect(flat(textOf(accounts))).toContain("Done");
  });

  it("WEB_6_world_render_a_town_and_a_village_have_no_Districts", async () => {
    const town = await mountWorld({ id: "northline" });
    expect(qa(town.el, 'section[aria-label="Districts"]')).toHaveLength(0);
    cleanup();
    const village = await mountWorld({ id: "calls" });
    expect(qa(village.el, 'section[aria-label="Districts"]')).toHaveLength(0);
  });
});

describe("WEB_6_world_render: Run history (Town)", () => {
  it("WEB_6_world_render_northline_runs_in_the_reference_order_with_cost", async () => {
    const { el } = await mountWorld({ id: "northline" });
    const section = region(el, "Run history");
    expect(textOf(q(section, "h2"))).toBe("Run history");
    expect(elWithText(section, "3 recent runs")).toBeTruthy();
    let last = -1;
    for (const [what, when, cost] of NORTHLINE_RUNS) {
      const row = rowOf(section, what, cost);
      expect(flat(textOf(row))).toBe(flat(`${what} ${when} ${cost}`));
      const at = textOf(section).indexOf(what);
      expect(at).toBeGreaterThan(last);
      last = at;
    }
    expect(textOf(section)).not.toContain(NO_RUNS);
  });

  it("WEB_6_world_render_a_failed_run_has_the_flag_icon_and_the_others_the_check", async () => {
    // Reference: icon(r.ok ? 'check' : 'flag'); tile okSoft/ok or amberTile/amberInk.
    const { el } = await mountWorld({ id: "invoice" });
    const section = region(el, "Run history");
    const art = (what: string, cost: string) =>
      rowOf(section, what, cost).querySelector(ART)?.outerHTML;
    const [r1, r2, r3] = INVOICE_RUNS;
    const flagged = art(r1?.[0] ?? "", r1?.[2] ?? "");
    const checkA = art(r2?.[0] ?? "", r2?.[2] ?? "");
    const checkB = art(r3?.[0] ?? "", r3?.[2] ?? "");
    expect(flagged).toBeTruthy();
    expect(checkA).toBeTruthy();
    expect(checkA).toBe(checkB);
    expect(flagged).not.toBe(checkA);
  });

  it("WEB_6_world_render_the_run_actions_are_Run_now_and_See_in_Agenda_under_the_list", async () => {
    const { el } = await mountWorld({ id: "invoice" });
    const section = region(el, "Run history");
    expect(hasControl(section, "Run now")).toBe(true);
    expect(hasControl(section, "See in Agenda")).toBe(true);
    const run = controls(section).find((e) => textOf(e) === "Run now");
    expect(run?.querySelector("svg"), "the play icon").not.toBeNull();
  });

  it("WEB_6_world_render_a_city_and_a_village_have_no_Run_history_or_run_buttons", async () => {
    const city = await mountWorld();
    expect(pageText(city.el)).not.toContain("Run now");
    expect(pageText(city.el)).not.toContain("See in Agenda");
    cleanup();
    const village = await mountWorld({ id: "calls" });
    expect(pageText(village.el)).not.toContain("Run now");
    expect(qa(village.el, 'section[aria-label="Run history"]')).toHaveLength(0);
  });
});

describe("WEB_6_world_render: Result (Village)", () => {
  it("WEB_6_world_render_a_running_task_shows_the_text_a_spinner_and_when_and_no_buttons", async () => {
    const { el } = await mountWorld({ id: "calls" });
    const section = region(el, "Result");
    expect(textOf(q(section, "h2"))).toBe("Result");
    // UI-10 B2: a sample is a recording: the header says Sample and the running line says whose state it is
    const recorded = `Recorded sample state: ${CALLS.mainSub}`;
    expect(textOf(section)).toContain(recorded);
    expect(elWithText(section, OUT.calls)).toBeTruthy();
    const line = elWithText(section, recorded);
    expect(line, "the running line").toBeTruthy();
    // spinner (an empty element) then the text, as in the reference
    const running = qa(section, "*").filter(
      (e) => textOf(e) === recorded && e.children.length >= 1,
    );
    expect(running.length, "a spinner element sits in the running line").toBeGreaterThanOrEqual(1);
    expect(hasControl(section, "Open result")).toBe(false);
    expect(hasControl(section, "Share to Slack")).toBe(false);
  });

  it("WEB_6_world_render_a_finished_task_shows_the_text_Open_result_and_Share_to_Slack_and_no_spinner", async () => {
    const { el } = await mountWorld({ id: "comp" });
    const section = region(el, "Result");
    expect(elWithText(section, OUT.comp)).toBeTruthy();
    expect(elWithText(section, COMP.mainSub)).toBeTruthy(); // the header's right side only
    expect(hasControl(section, "Open result")).toBe(true);
    expect(hasControl(section, "Share to Slack")).toBe(true);
    const shown = qa(section, "*").filter(
      (e) => textOf(e) === COMP.mainSub && ![...e.children].some((c) => textOf(c) === COMP.mainSub),
    );
    expect(shown, "the `when` text shows once, in the header").toHaveLength(1);
  });

  it("WEB_6_world_render_the_second_running_task_reads_its_own_numbers", async () => {
    const { el } = await mountWorld({ id: "venues" });
    const section = region(el, "Result");
    expect(elWithText(section, OUT.venues)).toBeTruthy();
    expect(elWithText(el, VENUES.progress)).toBeTruthy();
  });

  it("WEB_6_world_render_a_city_has_no_Result", async () => {
    const { el } = await mountWorld();
    expect(qa(el, 'section[aria-label="Result"]')).toHaveLength(0);
  });
});

describe("WEB_6_world_render: Activity", () => {
  it("WEB_6_world_render_K1_activity_in_the_reference_order", async () => {
    const { el } = await mountWorld();
    const section = region(el, "Activity");
    expect(textOf(q(section, "h2"))).toBe("Activity");
    expect(elWithText(section, "Today")).toBeTruthy();
    let last = -1;
    for (const [who, text, t] of K1_ACTIVITY) {
      const row = rowOf(section, text, t);
      expect(flat(textOf(row))).toBe(flat(`${who} ${text} ${t}`));
      expect(row.querySelector(ART), `${who}'s agent face`).not.toBeNull();
      const at = textOf(section).indexOf(text);
      expect(at).toBeGreaterThan(last);
      last = at;
    }
  });

  it("WEB_6_world_render_an_approval_puts_your_own_row_first_with_your_initials", async () => {
    const { el } = await mountWorld({ dec: { depot: true, mail: true } });
    const section = region(el, "Activity");
    const rows = [K1_ACTIVITY_DEPOT, K1_ACTIVITY_MAIL, ...K1_ACTIVITY];
    let last = -1;
    for (const [who, text, t] of rows) {
      const row = rowOf(section, text, t);
      const you = who === "You";
      expect(flat(textOf(row))).toBe(flat(`${you ? "AM " : ""}${who} ${text} ${t}`));
      const at = textOf(section).indexOf(text);
      expect(at).toBeGreaterThan(last);
      last = at;
    }
  });

  it("WEB_6_world_render_only_the_decided_one_adds_its_row", async () => {
    const { el } = await mountWorld({ dec: { mail: true } });
    const section = region(el, "Activity");
    expect(textOf(section)).toContain("Sent the supplier brief to 3 battery suppliers.");
    expect(textOf(section)).not.toContain("Approved £3,420 for Laptop Depot.");
  });

  it("WEB_6_world_render_a_world_without_activity_shows_one_Director_line_from_its_start", async () => {
    // UI-10 B3: the world's name keeps its own capitals (a lowercased "northline" was wrong), quoted
    const { el } = await mountWorld({ id: "calls" });
    const section = region(el, "Activity");
    const row = rowOf(section, "Started “Summarise yesterday’s calls”.", "09:04");
    expect(flat(textOf(row))).toBe(flat("Director Started “Summarise yesterday’s calls”. 09:04"));
    expect(row.querySelector(ART)).not.toBeNull();
  });

  it("UI_10_B3_the_default_activity_line_keeps_the_names_capitals", async () => {
    const { el } = await mountWorld({ id: "reply" });
    const text = textOf(region(el, "Activity"));
    expect(text).toContain("Started “Reply to Northline”.");
    expect(text).not.toContain("northline");
  });

  it("UI_10_B3_the_Activity_header_says_Today_only_when_every_row_is_from_today", async () => {
    const today = await mountWorld(); // K1: rows stamped with the time of day
    expect(textOf(q(region(today.el, "Activity"), ".park-world-sub"))).toBe("Today");
    cleanup();
    const older = await mountWorld({ id: "hires" }); // a row stamped "Yesterday"
    expect(textOf(q(region(older.el, "Activity"), ".park-world-sub"))).toBe("Recent");
  });

  it("UI_10_B3_a_project_with_a_budget_shows_spend_so_far_not_a_per_run_cost", async () => {
    const project = await mountWorld({ id: "northline" });
    expect(pageText(project.el)).toContain("£342 so far. Billed monthly.");
    expect(pageText(project.el)).not.toContain("Each run costs about £342");
    cleanup();
    const routine = await mountWorld({ id: "invoice" });
    expect(pageText(routine.el)).toContain("Each run costs about £0.60. Billed monthly.");
  });

  it("WEB_6_world_render_the_second_city_activity_has_its_three_rows", async () => {
    const { el } = await mountWorld({ id: "hires" });
    const section = region(el, "Activity");
    const row = rowOf(section, "Filed 12 HR records.", "Yesterday");
    expect(flat(textOf(row))).toBe(flat("Researcher Filed 12 HR records. Yesterday"));
    expect(
      elWithText(section, "Created Slack and email accounts for the last 3 starters."),
    ).toBeTruthy();
  });
});

describe("WEB_6_world_render: the Waiting for you card shows only what the world has open", () => {
  it("WEB_6_world_render_K1_card_title_count_and_both_decisions", async () => {
    const { el } = await mountWorld();
    expect(elWithText(el, "WAITING FOR YOU")).toBeTruthy();
    expect(elWithText(el, "2 decisions before agents continue")).toBeTruthy();
    for (const d of Object.values(DECISIONS)) {
      expect(elWithText(el, d.title), d.title).toBeTruthy();
      expect(elWithText(el, d.body), d.body).toBeTruthy();
      expect(hasControl(el, d.yes), d.yes).toBe(true);
    }
    expect(controls(el).filter((e) => textOf(e) === "Ask me later")).toHaveLength(2);
  });

  it("WEB_6_world_render_a_world_with_no_open_decision_has_no_card", async () => {
    for (const id of ["hires", "northline", "invoice", "calls", "audit"]) {
      const { el } = await mountWorld({ id });
      expect(pageText(el), id).not.toContain("WAITING FOR YOU");
      expect(pageText(el), id).not.toContain("Ask me later");
      cleanup();
    }
  });

  it("WEB_6_world_render_once_every_decision_is_taken_the_card_goes", async () => {
    const { el } = await mountWorld({ dec: { depot: true, mail: true } });
    expect(pageText(el)).not.toContain("WAITING FOR YOU");
    expect(pageText(el)).not.toContain("before agents continue");
  });
});
