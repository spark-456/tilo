// @vitest-environment happy-dom
// WEB-4 acceptance: what the Home page shows. Pinned to the user's design, not to an implementation:
//   design_handoff_tilo_web_app/design/Tilo App Home.dc.html (the reference page and its data in tilo-app.js),
//   README "Home" and inventory.md "Tilo App Home.dc.html" (regions and static copy).
// Pinned module surface: src/park/pages/Home/HomePage.tsx exports `HomePage({ app }: { app: AppCtx })`;
// the page renders inside ParkProvider (it reads data through useParkApi) and draws its panels only:
// no <main>, no PageSheet, no h1 other than the greeting, no chip (the shell shows "Sample data").
// Reference behaviours kept on purpose, see the WEB-4 report: the "Needs you" element is one amber pill
// ("N decisions waiting in K1 electric scooter" + Review), not a list of decision cards; "Up next today"
// takes the first two events after 09:18 in fixture order; the side panel needs a viewport of 1180 or more.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import { LIVE_OPEN, QUICK, UP_NEXT } from "../../../../test-support/park/homeCopy";
import {
  NIGHT,
  clickEl,
  control,
  controlWith,
  elWithText,
  flat,
  mountHome,
  pageText,
  progressOf,
  settle,
  sizeGroup,
  type spiedApi,
  taskInput,
  textOf,
  todayRegion,
} from "../../../../test-support/park/homeHarness";
import { HANDOFF_DIR } from "../../../../test-support/park/prototype";
import { makeWorld } from "../../api/fixtures";

afterEach(cleanup);

const SUMMARY_DAY_2 = "38 agents are at work across 4 worlds. Two things need you.";
const SUMMARY_NIGHT_2 = "Your city keeps working overnight. Two things need you before morning.";

describe("WEB_4_home_render: regions and landmarks", () => {
  it("WEB_4_home_render_labelled_regions_Today_Describe_your_task_Size_of_job", async () => {
    const { el } = await mountHome();
    const today = todayRegion(el);
    expect(today.tagName).toBe("ASIDE");
    expect(taskInput(el).type).toBe("text");
    const size = sizeGroup(el);
    expect(["radiogroup", "tablist"]).toContain(size.getAttribute("role"));
  });

  it("WEB_4_home_render_the_page_draws_panels_only_no_main_no_page_sheet_one_h1", async () => {
    const { el } = await mountHome();
    expect(qa(el, "main")).toHaveLength(0); // the landmark belongs to the shell
    expect(qa(el, ".park-sheet")).toHaveLength(0); // Home floats glass panels, it has no PageSheet
    expect(qa(el, "h1")).toHaveLength(1);
  });

  it("WEB_4_home_render_the_root_carries_the_registry_testid_park_page_home", async () => {
    // The Placeholder and the 3a e2e use data-testid="park-page-<id>" for the page root.
    const { el } = await mountHome();
    expect(qa(el, '[data-testid="park-page-home"]')).toHaveLength(1);
  });

  it("WEB_4_home_render_no_sample_data_chip_in_the_page_the_shell_owns_it", async () => {
    const { el } = await mountHome();
    expect(pageText(el)).not.toMatch(/sample data/i);
  });
});

describe("WEB_4_home_render: the greeting panel", () => {
  it("WEB_4_home_render_day_date_greeting_and_summary_come_from_the_fixtures", async () => {
    const { el } = await mountHome();
    expect(textOf(q(el, "h1"))).toBe("Good morning, Alex.");
    expect(
      elWithText(el, "Thursday 24 September", true),
      "the date line, from `today`",
    ).toBeTruthy();
    expect(elWithText(el, SUMMARY_DAY_2), "the summary line").toBeTruthy();
  });

  it("WEB_4_home_render_night_copy_is_the_evening_one_with_the_21_10_clock", async () => {
    const { el } = await mountHome({ app: NIGHT });
    expect(textOf(q(el, "h1"))).toBe("Good evening, Alex.");
    expect(elWithText(el, "Thursday 24 September · 21:10", true)).toBeTruthy();
    expect(elWithText(el, SUMMARY_NIGHT_2)).toBeTruthy();
    expect(pageText(el)).not.toContain("Good morning");
  });

  it("WEB_4_home_render_two_open_decisions_show_the_amber_needs_pill_with_Review", async () => {
    const { el } = await mountHome();
    const pill = controlWith(el, "in K1 electric scooter");
    expect(pill.tagName).toBe("BUTTON");
    expect(flat(textOf(pill))).toBe(flat("2 decisions waiting in K1 electric scooter Review"));
    expect(pill.querySelector("svg, img"), "the builder agent’s face in the pill").not.toBeNull();
    expect(pageText(el)).not.toContain("You’re all caught up");
  });
});

describe("WEB_4_home_render: Today panel", () => {
  it("WEB_4_home_render_live_now_lists_the_five_worlds_with_their_lines_and_progress", async () => {
    const { el } = await mountHome();
    const today = todayRegion(el);
    expect(textOf(today)).toContain("Sample worlds"); // fixture rows: never titled "Live now" (HR-1)
    let last = -1;
    for (const w of LIVE_OPEN) {
      const row = controlWith(today, w.name);
      expect(flat(textOf(row)), w.name).toBe(flat(`${w.name} ${w.sub}`));
      expect(progressOf(row), `${w.name} progress`).toBe(w.prog);
      expect(row.querySelector("svg, img"), `${w.name} art`).not.toBeNull();
      const at = textOf(today).indexOf(w.name);
      expect(at, `${w.name} keeps the reference order`).toBeGreaterThan(last);
      last = at;
    }
  });

  it("WEB_4_home_render_live_now_leaves_out_finished_and_scheduled_worlds", async () => {
    const { el } = await mountHome();
    const text = textOf(todayRegion(el));
    for (const gone of [
      "Q3 audit prep",
      "Invoice match",
      "Inbox triage",
      "Pricing check",
      "Northline reply",
    ]) {
      expect(text, gone).not.toContain(gone);
    }
  });

  it("WEB_4_home_render_up_next_today_shows_the_first_two_events_after_09_18", async () => {
    const { el } = await mountHome();
    const today = todayRegion(el);
    expect(textOf(today)).toContain("Up next today");
    for (const e of UP_NEXT) {
      const row = controlWith(today, e.title);
      expect(flat(textOf(row)), e.title).toBe(flat(`${e.time} ${e.title} ${e.sub}`));
    }
    const text = textOf(today);
    expect(text).not.toContain("Read Tilo’s brief"); // third in the day: the reference shows two
    expect(text).not.toContain("Team stand-up"); // 09:00 is before 09:18
  });

  it("WEB_4_home_render_september_spend_shows_the_ledger_numbers", async () => {
    const { el } = await mountHome();
    const spend = controlWith(todayRegion(el), "September spend");
    expect(spend.tagName).toBe("BUTTON");
    const text = textOf(spend);
    for (const part of [
      "September spend",
      "Ledger",
      "£2,412",
      "of £8,000",
      "Forecast £6,300 · £3,420 waiting on you",
    ]) {
      expect(text, part).toContain(part);
    }
  });

  it("WEB_4_home_render_sections_follow_the_reference_order", async () => {
    const { el } = await mountHome();
    const today = textOf(todayRegion(el));
    expect(today.indexOf("Sample worlds")).toBeLessThan(today.indexOf("Up next today"));
    expect(today.indexOf("Up next today")).toBeLessThan(today.indexOf("September spend"));
    const page = pageText(el);
    expect(page.indexOf("Good morning")).toBeLessThan(page.indexOf("Sample worlds"));
    expect(page.indexOf("September spend")).toBeLessThan(page.indexOf(QUICK.start));
  });

  // UI-10 / A2 (14 Oct QA): this test used to say the Today panel and the spend tiles are left out under 1180.
  // A tablet or a phone must see the same numbers, so they render at every width and CSS stacks them.
  it("UI_10_A2_home_render_the_today_panel_and_the_spend_tiles_render_at_every_width", async () => {
    for (const vw of [1440, 1180, 1179, 1024, 768, 390]) {
      const { el } = await mountHome({ app: { vw } });
      expect(qa(el, 'aside[aria-label="Today"]'), `Today panel at ${vw}`).toHaveLength(1);
      expect(qa(el, '[aria-label="Spend at a glance"] .park-kpi'), `tiles at ${vw}`).toHaveLength(
        5,
      );
      expect(textOf(q(el, "h1"))).toBe("Good morning, Alex.");
      expect(taskInput(el)).toBeTruthy();
      cleanup();
    }
  });

  it("WEB_4_home_render_a_started_world_leads_the_live_list_and_the_list_stays_at_five", async () => {
    const added = makeWorld("quick", "Compare three suppliers", 1);
    const { el, api } = await mountHome({ app: { added: [added] } });
    const today = todayRegion(el);
    const first = controlWith(today, "Compare three suppliers");
    expect(flat(textOf(first))).toBe(flat("Compare three suppliers Starting now"));
    expect(progressOf(first)).toBe(4);
    const text = textOf(today);
    expect(text.indexOf("Compare three suppliers")).toBeLessThan(
      text.indexOf("K1 electric scooter"),
    );
    expect(text).not.toContain("Venue options"); // pushed out: five rows at most
    for (const w of LIVE_OPEN.slice(0, 4)) expect(text, w.name).toContain(w.name);
    const calls = (api as ReturnType<typeof spiedApi>).getWorlds.mock.calls;
    const lastCall = calls[calls.length - 1];
    expect(lastCall?.[1], "the Api is asked with the started worlds").toEqual([added]);
  });
});

describe("WEB_4_home_render: inventory.md", () => {
  const inventory = readFileSync(join(HANDOFF_DIR, "inventory.md"), "utf8");
  const section = inventory.split(/^## /m).find((s) => s.startsWith("Tilo App Home.dc.html")) ?? "";
  const copyBlock = (section.split("- Static copy:")[1] ?? "").split("- Toast messages")[0] ?? "";
  const staticCopy = copyBlock
    .split("\n")
    .map((l) => /^\s+- (.+)$/.exec(l)?.[1])
    .filter((s): s is string => Boolean(s));

  it("WEB_4_home_render_inventory_parse_found_the_home_section", () => {
    expect(staticCopy.length).toBeGreaterThanOrEqual(13);
    expect(section).toContain("Labelled regions: Today · Describe your task · Size of job");
  });

  it("WEB_4_home_render_every_static_string_of_the_inventory_appears_in_its_state", async () => {
    const rig = await mountHome();
    // Needs state, plan open: the pill, Review and "Change brief".
    clickEl(control(rig.el, QUICK.start));
    await settle();
    rig.sch.fire(rig.sch.timers.find((t) => t.ms === 900));
    await settle();
    const withNeeds = pageText(rig.el);
    await rig.setDec({ depot: true, mail: true });
    const caughtUp = pageText(rig.el);
    // the design's "Live now" is the live path's title; the fixture panel carries the sample title instead
    for (const s of staticCopy.map((c) => (c === "Live now" ? "Sample worlds" : c))) {
      expect(`${withNeeds} ${caughtUp}`, `inventory string "${s}"`).toContain(s);
    }
    expect(withNeeds).toContain("Review");
    expect(withNeeds).toContain("Change brief");
    expect(caughtUp).toContain("You’re all caught up");
    expect(caughtUp).not.toContain("in K1 electric scooter");
  });
});
