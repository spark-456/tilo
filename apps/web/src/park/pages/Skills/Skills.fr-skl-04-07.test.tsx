// @vitest-environment happy-dom
// Acceptance tests for AGY-SKL-2 (FR-SKL-04, FR-SKL-05, FR-SKL-06, FR-SKL-07):
// - FR-SKL-04: save with name, scope (just me / team), trigger (when I ask / schedule / event);
//   a saved skill starts as Learning and appears in the library.
// - FR-SKL-05: thumbs up/down; a thumbs down asks which step went wrong; the fix applies to the
//   next run of that skill and is logged.
// - FR-SKL-06: run-history bars, Mark as trusted / Keep learning, Pause / Resume; a paused skill
//   never starts; trusted needs a set number of good runs (in config, not code).
// - FR-SKL-07: who helped this month: answers and fixes per person, with the change in mistakes;
//   counts only, never message content.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  choice,
  clickEl,
  control,
  elWithText,
  fixtureResult,
  hasControl,
  isDisabled,
  isOn,
  mountSkills,
  pageText,
  skillNameField,
  skillsApi,
  textOf,
  toSave,
  toasts,
  typeInto,
} from "../../../../test-support/park/skillsHarness";
import { learn, skills } from "../../api/fixtures";
import * as skillConfig from "./skillConfig";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const helpSection = (root: ParentNode): HTMLElement =>
  q(root, 'section[aria-label="Help your agents get better"]');
const librarySection = (root: ParentNode): HTMLElement =>
  q(root, 'section[aria-label="Learned skills"]');

describe("FR-SKL-04: Save a skill and Learned skills library", () => {
  it("test_FR_SKL_04_save_skill_with_name_scope_and_trigger_starts_as_learning_and_appears_in_library", async () => {
    const rig = await mountSkills();
    const api = rig.api as ReturnType<typeof skillsApi>;

    // Before saving, draft skill "Log new supplier invoices" is in the library as Draft
    const libBefore = librarySection(rig.el);
    expect(pageText(libBefore)).toContain("Log new supplier invoices");
    expect(pageText(libBefore)).toContain("Draft");

    // Complete teach flow to Save step, configure name, scope, and trigger
    toSave(rig);
    typeInto(skillNameField(rig.el), "Auto-log supplier invoices");
    clickEl(choice(rig.el, "Just me"));
    clickEl(choice(rig.el, "Weekdays 09:00"));
    clickEl(control(rig.el, "Save skill"));

    expect(api.saveSkill).toHaveBeenCalledTimes(1);
    expect(api.saveSkill.mock.calls[0]?.[0]).toMatchObject({
      id: "log",
      name: "Auto-log supplier invoices",
      st: "learning",
      status: "live",
      runs: 1,
      rate: 100,
    });

    // Saved skill appears in the library as Learning and is selected
    const libAfter = librarySection(rig.el);
    expect(pageText(libAfter)).toContain("Auto-log supplier invoices");
    expect(pageText(libAfter)).toContain("FINANCE · LEARNING");
    expect(pageText(libAfter)).toContain("Owned by Alex Morgan · learned from taught by you");
    expect(pageText(libAfter)).toContain("£0.38 a run");
  });

  it("test_FR_SKL_04_learned_skills_library_search_and_selection_shows_steps_and_cost", async () => {
    const rig = await mountSkills();
    const lib = librarySection(rig.el);
    const search = q<HTMLInputElement>(lib, 'input[aria-label="Search skills"]');

    // Filter skills by search query
    typeInto(search, "competitor");
    expect(pageText(lib)).toContain("Scan competitor prices");
    expect(pageText(lib)).not.toContain("Summarise call notes");

    // Select "Scan competitor prices" and inspect detail view
    const rowBtn = qa(lib, "button").find((b) => textOf(b).startsWith("Scan competitor prices"));
    expect(rowBtn).toBeDefined();
    clickEl(rowBtn as HTMLElement);
    expect(pageText(lib)).toContain("SALES · TRUSTED");
    expect(pageText(lib)).toContain("Open the 14 competitor product pages");
    expect(pageText(lib)).toContain("49% cheaper than the first run");
  });
});

describe("FR-SKL-05: Rate and fix runs", () => {
  it("test_FR_SKL_05_thumbs_up_and_thumbs_down_step_picker_logs_fix_and_applies_to_next_run", async () => {
    const rig = await mountSkills();
    const help = helpSection(rig.el);

    const goodBtns = qa(help, 'button[aria-label="Good run"]');
    const wrongBtns = qa(help, 'button[aria-label="Something went wrong"]');
    expect(goodBtns).toHaveLength(4);
    expect(wrongBtns).toHaveLength(4);

    // Thumbs up on second run ("Scan competitor prices")
    clickEl(goodBtns[1] as HTMLElement);
    expect(isOn(goodBtns[1] as HTMLElement)).toBe(true);

    // Thumbs down on first run ("Triage the Accounts inbox") opens step picker
    clickEl(wrongBtns[0] as HTMLElement);
    expect(isOn(wrongBtns[0] as HTMLElement)).toBe(true);
    expect(pageText(help)).toContain("Which step went wrong?");
    for (const stepLabel of ["Sort mail", "Draft replies", "Flag urgent"]) {
      expect(hasControl(help, stepLabel)).toBe(true);
    }

    // Pick step "Draft replies", enter replacement instruction, and save fix
    clickEl(control(help, "Draft replies"));
    expect(isOn(control(help, "Draft replies"))).toBe(true);
    const fixInput = q<HTMLTextAreaElement>(
      help,
      'textarea[aria-label="What should it do instead"]',
    );
    typeInto(fixInput, "Check PO status before drafting reply");
    clickEl(control(help, "Save fix"));

    // Drawer closes, "Fix saved" badge appears, toast announces next run uses it
    expect(pageText(help)).not.toContain("Which step went wrong?");
    expect(pageText(help)).toContain("Fix saved");
    expect(toasts(rig.app)).toContainEqual(["Fix saved. The next run uses it"]);

    // Select "Triage the Accounts inbox" in the library: the logged fix is applied to its step and next run
    const lib = librarySection(rig.el);
    const triageRow = qa(lib, "button").find((b) =>
      textOf(b).startsWith("Triage the Accounts inbox"),
    );
    clickEl(triageRow as HTMLElement);
    expect(pageText(lib)).toContain("Check PO status before drafting reply");
  });
});

describe("FR-SKL-06: Trust and pause", () => {
  it("test_FR_SKL_06_ready_for_review_run_history_bars_mark_as_trusted_and_keep_learning", async () => {
    const rig = await mountSkills();
    const help = helpSection(rig.el);
    const lib = librarySection(rig.el);

    // Run-history bars are rendered for both review items (12 bars + 6 bars)
    const barCharts = qa(help, '[role="img"]');
    expect(barCharts).toHaveLength(2);
    expect(barCharts[0]?.children).toHaveLength(12);
    expect(barCharts[1]?.children).toHaveLength(6);

    // Click "Mark as trusted" on the first review item ("Draft a supplier brief")
    const trustBtns = qa(help, "button").filter((b) => textOf(b) === "Mark as trusted");
    expect(trustBtns).toHaveLength(2);
    clickEl(trustBtns[0] as HTMLElement);

    expect(pageText(help)).toContain("Trusted. Tilo stops asking before routine steps.");
    expect(toasts(rig.app)).toContainEqual(["“Draft a supplier brief” is trusted"]);
    expect(elWithText(rig.el, "5 trusted")).toBeDefined();

    // Select "Draft a supplier brief" in library -> now Trusted
    const briefRow = qa(lib, "button").find((b) => textOf(b).startsWith("Draft a supplier brief"));
    clickEl(briefRow as HTMLElement);
    expect(pageText(lib)).toContain("SUPPLY CHAIN · TRUSTED");

    // Click "Keep learning" on the second review item ("Check firmware test results")
    clickEl(control(help, "Keep learning"));
    expect(pageText(help)).toContain("Still learning. Tilo checks again after 5 more runs.");
  });

  it("test_FR_SKL_06_trusted_requires_configured_number_of_good_runs_from_config", async () => {
    expect(Object.keys(skillConfig.SKILL_TRUST_CONFIG)).toEqual(["minGoodRunsForTrust"]);
    expect(skillConfig.SKILL_TRUST_CONFIG.minGoodRunsForTrust).toBe(5);
    expect(skillConfig.canTrustSkill([1, 1, 1, 1, 1])).toBe(true);
    expect(skillConfig.canTrustSkill([1, 1, 0, 1])).toBe(false);

    // When a review item has fewer than minGoodRunsForTrust good runs, "Mark as trusted" is disabled
    const api = skillsApi({
      getSkills: () => fixtureResult(skills),
      getLearn: () =>
        fixtureResult({
          ...learn,
          reviews: [{ id: "brief", meta: "4 runs · 3 good", bars: [1, 1, 0, 1] }],
        }),
    });
    const rig = await mountSkills({ api });
    const help = helpSection(rig.el);
    const trustBtn = control(help, "Mark as trusted");
    expect(isDisabled(trustBtn)).toBe(true);
    clickEl(trustBtn);
    expect(pageText(help)).not.toContain("Trusted. Tilo stops asking before routine steps.");
  });

  it("test_FR_SKL_06_pause_and_resume_and_paused_skill_never_starts", async () => {
    const rig = await mountSkills();
    const lib = librarySection(rig.el);

    // Pause the currently selected skill ("Match invoices to purchase orders")
    clickEl(control(lib, "Pause"));
    expect(pageText(lib)).toContain("FINANCE · PAUSED");
    expect(toasts(rig.app)).toContainEqual([
      "“Match invoices to purchase orders” is paused. Worlds using it will ask you instead",
    ]);

    // While paused, "Test run" is disabled and clicking it never starts a run
    const testRunBtn = control(lib, "Test run");
    expect(isDisabled(testRunBtn)).toBe(true);
    const toastCountAfterPause = toasts(rig.app).length;
    clickEl(testRunBtn);
    expect(toasts(rig.app)).toHaveLength(toastCountAfterPause);

    // Resume the skill -> can run again
    clickEl(control(lib, "Resume"));
    expect(pageText(lib)).toContain("FINANCE · TRUSTED");
    expect(toasts(rig.app)).toContainEqual([
      "“Match invoices to purchase orders” is running again",
    ]);
    expect(isDisabled(control(lib, "Test run"))).toBe(false);
    clickEl(control(lib, "Test run"));
    expect(toasts(rig.app)).toContainEqual([
      "Test run started on yesterday’s data. Results in about a minute",
    ]);
  });
});

describe("FR-SKL-07: Who helped this month", () => {
  it("test_FR_SKL_07_who_helped_this_month_shows_counts_and_mistake_change_only_never_message_content", async () => {
    const fixtures = (await import("../../api/fixtures")) as Record<string, unknown>;
    const teachData = (await import("./teachData")) as Record<string, unknown>;
    expect(fixtures.HELPER_SUMMARY_FIXTURE).toEqual({
      baseMonthlyAnswersAndFixes: 41,
      mistakesDeltaSinceJuly: "−38%",
      helperMonthLabel: "September",
    });
    expect(teachData.HELPER_SUMMARY_FIXTURE).toBeUndefined();

    const rig = await mountSkills();
    const help = helpSection(rig.el);
    const whoCard = elWithText(help, "Who helped this month")?.closest(
      ".park-skills-help-card",
    ) as HTMLElement;
    expect(whoCard).toBeTruthy();

    expect(pageText(whoCard)).toContain("Mistakes since July");
    expect(pageText(whoCard)).toContain("−38%");
    expect(pageText(whoCard)).toContain("Answers and fixes");
    expect(pageText(whoCard)).toContain("41");
    expect(pageText(whoCard)).toContain("Alex Morgan (you)");
    expect(pageText(whoCard)).toContain("28");
    expect(pageText(whoCard)).toContain("Priya Shah");
    expect(pageText(whoCard)).toContain("17");

    // Answer a saved-up question and submit a fix with custom message text
    clickEl(control(help, "Yes, include shipping"));
    const wrongBtns = qa(help, 'button[aria-label="Something went wrong"]');
    clickEl(wrongBtns[0] as HTMLElement);
    clickEl(control(help, "Sort mail"));
    const fixInput = q<HTMLTextAreaElement>(
      help,
      'textarea[aria-label="What should it do instead"]',
    );
    typeInto(fixInput, "CONFIDENTIAL_MESSAGE_BODY_NEVER_SHOW_IN_HELPER_CARD");
    clickEl(control(help, "Save fix"));

    // Counts update (+1 answer, +1 rating, +1 fix = +3 -> 44 total, 31 for Alex Morgan (you))
    expect(pageText(whoCard)).toContain("44");
    expect(pageText(whoCard)).toContain("31");
    // Never renders message content or free-text fix body in Who helped this month
    expect(pageText(whoCard)).not.toContain("CONFIDENTIAL_MESSAGE_BODY_NEVER_SHOW_IN_HELPER_CARD");
    expect(pageText(whoCard)).not.toContain("Yes, include shipping");
  });
});
