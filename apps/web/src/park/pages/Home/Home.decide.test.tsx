// @vitest-environment happy-dom
// WEB-4 acceptance: what a decision changes on Home. `decide(key)` is the one approval call (README "The
// `app` prop"); Home reads `app.dec` and shows it in exactly the places the reference does: the amber needs
// pill (or "You’re all caught up"), the summary line, the K1 row of "Live now" and the K1 map pin. The
// September spend panel does NOT change in the reference (its numbers are fixed in the page); that is
// pinned here as the design, and listed in the WEB-4 report as an ambiguity against the Ledger page.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  NIGHT,
  controlWith,
  elWithText,
  flat,
  hasControl,
  mountHome,
  pageText,
  pinFor,
  progressOf,
  spiedApi,
  textOf,
  todayRegion,
} from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

const DAY = "38 agents are at work across 4 worlds. ";
const NIGHT_LINE = "Your city keeps working overnight. ";
// UI-STUDIO-2: the K1 world is a card in the Sample worlds section.
const k1Row = (el: HTMLElement) =>
  controlWith(
    el.querySelector('section[aria-label="Sample worlds"]') as HTMLElement,
    "K1 electric scooter",
  );

describe("WEB_4_home_decide: the Needs-you pill and the caught-up state", () => {
  it("WEB_4_home_decide_one_approval_leaves_one_decision_in_the_singular", async () => {
    for (const dec of [{ depot: true }, { mail: true }]) {
      const rig = await mountHome({ dec });
      const pill = controlWith(rig.el, "in K1 electric scooter");
      expect(flat(textOf(pill))).toBe(flat("1 decision waiting in K1 electric scooter Review"));
      expect(pageText(rig.el)).not.toContain("2 decisions");
      expect(pageText(rig.el)).not.toContain("You’re all caught up");
      cleanup();
    }
  });

  it("WEB_4_home_decide_both_approved_replaces_the_pill_with_all_caught_up", async () => {
    const rig = await mountHome({ dec: { depot: true, mail: true } });
    const text = pageText(rig.el);
    expect(text).toContain("You’re all caught up");
    expect(text).not.toContain("in K1 electric scooter");
    expect(text).not.toContain("decision waiting");
    expect(text).not.toMatch(/\bReview\b/);
    expect(elWithText(rig.el, "You’re all caught up")).toBeTruthy();
  });

  it("WEB_4_home_decide_a_decision_changing_after_mount_updates_the_page_both_ways", async () => {
    const rig = await mountHome();
    expect(pageText(rig.el)).toContain("2 decisions waiting in K1 electric scooter");
    await rig.setDec({ depot: true });
    expect(pageText(rig.el)).toContain("1 decision waiting in K1 electric scooter");
    await rig.setDec({ depot: true, mail: true });
    expect(pageText(rig.el)).toContain("You’re all caught up");
    await rig.setDec({ mail: true }); // Undo on the toast
    expect(pageText(rig.el)).not.toContain("You’re all caught up");
    expect(pageText(rig.el)).toContain("1 decision waiting in K1 electric scooter");
    await rig.setDec({});
    expect(pageText(rig.el)).toContain("2 decisions waiting in K1 electric scooter");
  });

  it("WEB_4_home_decide_the_worlds_are_read_again_for_the_new_decisions", async () => {
    const api = spiedApi();
    const rig = await mountHome({ api });
    await rig.setDec({ depot: true, mail: true });
    expect(api.getWorlds.mock.calls.at(-1)?.[0]).toEqual({ depot: true, mail: true });
  });
});

describe("WEB_4_home_decide: the summary line", () => {
  it.each([
    [{}, `${DAY}Two things need you.`],
    [{ depot: true }, `${DAY}One thing needs you.`],
    [{ mail: true }, `${DAY}One thing needs you.`],
    [{ depot: true, mail: true }, `${DAY}Nothing needs you right now.`],
  ])("WEB_4_home_decide_day_summary_for_dec_%j", async (dec, line) => {
    const rig = await mountHome({ dec });
    expect(elWithText(rig.el, line), line).toBeTruthy();
  });

  it.each([
    [{}, `${NIGHT_LINE}Two things need you before morning.`],
    [{ depot: true }, `${NIGHT_LINE}One thing needs you before morning.`],
    [{ depot: true, mail: true }, `${NIGHT_LINE}Nothing needs you.`],
  ])("WEB_4_home_decide_night_summary_for_dec_%j", async (dec, line) => {
    const rig = await mountHome({ dec, app: NIGHT });
    expect(elWithText(rig.el, line), line).toBeTruthy();
  });
});

describe("WEB_4_home_decide: the K1 row of Live now", () => {
  it("WEB_4_home_decide_k1_row_counts_the_waiting_decisions", async () => {
    const open = await mountHome();
    expect(flat(textOf(k1Row(open.el)))).toBe(
      flat("Needs you K1 electric scooter 2 decisions waiting 46%"),
    );
    cleanup();
    const one = await mountHome({ dec: { depot: true } });
    expect(flat(textOf(k1Row(one.el)))).toBe(
      flat("Needs you K1 electric scooter 1 decision waiting 46%"),
    );
  });

  it("WEB_4_home_decide_k1_row_goes_back_to_running_when_nothing_is_waiting", async () => {
    const rig = await mountHome({ dec: { depot: true, mail: true } });
    const row = k1Row(rig.el);
    expect(flat(textOf(row))).toBe(flat("Working K1 electric scooter Running · 46% 46%"));
  });
});

describe("STUDIO_2_home_decide: the Needs you card follows the decisions", () => {
  const needsCard = (el: HTMLElement) => el.querySelector(".park-home-card--needs") as HTMLElement;
  it.each([
    [{}, 2],
    [{ depot: true }, 1],
    [{ depot: true, mail: true }, 0],
  ] as const)("STUDIO_2_home_decide_needs_card_for_dec_%j", async (dec, open) => {
    const rig = await mountHome({ dec });
    const card = needsCard(rig.el);
    expect(card.querySelectorAll(".park-home-tray")).toHaveLength(open);
    if (open > 0)
      expect(textOf(card.querySelector(".park-home-count") as Element)).toBe(String(open));
    else expect(textOf(card)).toContain("Nothing needs you right now.");
  });
});

describe("WEB_4_home_decide: the spend panel is the reference's fixed one", () => {
  it.each([{}, { depot: true }, { mail: true }, { depot: true, mail: true }])(
    "WEB_4_home_decide_spend_panel_text_is_the_same_for_dec_%j",
    async (dec) => {
      const rig = await mountHome({ dec });
      const spend = textOf(controlWith(todayRegion(rig.el), "September spend"));
      for (const part of ["£2,412", "of £8,000", "Forecast £6,300 · £3,420 waiting on you"]) {
        expect(spend, part).toContain(part);
      }
    },
  );
});
