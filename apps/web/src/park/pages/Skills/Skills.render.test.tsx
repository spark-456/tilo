// @vitest-environment happy-dom
// WEB-8a acceptance: what the Skills page shows in its header and in the "Teach Tilo something new" card
// before anything is done. Pinned to the user's design, not to an implementation:
//   design_handoff_tilo_web_app/design/Tilo App Skills.dc.html (markup and `renderVals`; the reference page),
//   README "Skills" items 1 and 2, inventory.md "Tilo App Skills.dc.html" (labelled regions, static copy).
// Pinned module surface: src/park/pages/Skills/SkillsPage.tsx exports `SkillsPage({ app }: { app: AppCtx })`;
// it renders inside ParkProvider (data through useParkApi), draws the sheet's content only (a PageSheet, no
// <main>, exactly one h1) and shows no "Sample data" chip (the shell does). WEB-8b adds the sections below
// the Teach card, WEB-8c the library and the tools: nothing here pins them.
// Reference behaviours kept on purpose (see the WEB-8a report): the Teach card has no closed state (it is the
// open card; "Teach a skill" scrolls to it); the counts in the pills come from the skills' `st`, not `status`.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import { INTRO } from "../../../../test-support/park/skillsCopy";
import {
  NIGHT,
  control,
  elWithText,
  fixtureResult,
  flat,
  goCalls,
  mountSkills,
  openSkill,
  pageText,
  pendingApi,
  rejects,
  skillsApi,
  textOf,
  toasts,
} from "../../../../test-support/park/skillsHarness";
import { learn, skills } from "../../api/fixtures";
import { skillsOfBody } from "../../api/live/skillsFromApi";
import { createLiveApi } from "../../api/liveApi";
import type { Skill } from "../../api/types";

it("LIVE-SKILLS renders builtins as shipped descriptions with run and edit controls disabled", async () => {
  const list = skillsOfBody({
    skills: [],
    builtins: [{ id: "web-research", version: "1.0.0", description: "Research public sources." }],
  });
  const { el } = await mountSkills({
    api: skillsApi({ getSkills: () => fixtureResult(list ?? []) }),
  });
  expect(el.textContent).toContain("Web Research");
  expect(el.textContent).toContain("Research public sources.");
  // STUDIO-4: the detail is a side sheet; a built-in offers no run, pause or step edit at all.
  const drawer = openSkill(el, "Web Research");
  expect(drawer.textContent).toContain("Shipped with Tilo · version 1.0.0");
  expect(drawer.textContent).toContain("Built-in skills are picked by agents during a run.");
  for (const text of ["Try run", "Test run", "Pause", "Edit steps"]) {
    const button = Array.from(drawer.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === text,
    );
    expect(button, text).toBeUndefined();
  }
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const skill = (id: string): Skill => {
  const hit = skills.find((s) => s.id === id);
  if (!hit) throw new Error(`no fixture skill ${id}`);
  return hit;
};
const COUNT = /\b\d+ (skills|trusted|learning|need your help)\b|Nothing waiting/;

describe("WEB_8a_skills_render: the page frame", () => {
  it("WEB_8a_skills_render_the_root_carries_the_registry_testid_from_the_first_render", async () => {
    const { el } = await mountSkills({ api: pendingApi() });
    expect(qa(el, '[data-testid="park-page-skills"]')).toHaveLength(1);
  });

  it("WEB_8a_skills_render_no_main_a_page_sheet_and_exactly_one_h1_named_Skills", async () => {
    for (const api of [skillsApi(), pendingApi()]) {
      const { el } = await mountSkills({ api });
      expect(qa(el, "main")).toHaveLength(0); // the landmark belongs to the shell
      expect(qa(el, ".park-skills-page")).toHaveLength(1); // STUDIO-4: the Studio page frame
      const h1s = qa(el, "h1");
      expect(h1s).toHaveLength(1);
      expect(textOf(h1s[0] as HTMLElement)).toBe("Skills");
      cleanup();
    }
  });

  it("WEB_8a_skills_render_the_total_sits_beside_the_h1_and_counts_all_skills_the_Api_returned", async () => {
    const { el } = await mountSkills();
    const h1 = q(el, "h1");
    expect(flat(textOf(h1.parentElement as HTMLElement))).toBe(`Skills${skills.length}skills`);
    expect(skills.length).toBe(8); // the sample data: the page shows "8 skills"
  });

  it("WEB_8a_skills_render_the_intro_line_is_the_designs", async () => {
    const { el } = await mountSkills();
    const intro = elWithText(el, INTRO);
    expect(intro?.tagName).toBe("P");
  });

  it("WEB_8a_skills_render_header_order_is_title_then_pills_and_button_then_the_Teach_card", async () => {
    const { el } = await mountSkills();
    const follows = (a: Element, b: Element) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    const h1 = q(el, "h1");
    const pill = elWithText(el, "4 trusted") as HTMLElement;
    const button = q(el, "button");
    expect(textOf(button)).toBe("+ Teach Tilo a skill"); // STUDIO-4: the first control, the one primary
    expect(follows(h1, button)).toBe(true);
    expect(follows(button, pill)).toBe(true);
    expect(follows(pill, q(el, 'section[aria-label="Teach Tilo a skill"]'))).toBe(true);
  });

  it("WEB_8a_skills_render_nothing_is_called_or_announced_on_mount_and_no_chip_is_drawn", async () => {
    const rig = await mountSkills();
    expect(goCalls(rig.app)).toEqual([]);
    expect(toasts(rig.app)).toEqual([]);
    expect(pageText(rig.el)).not.toMatch(/sample data/i); // the shell shows the chip
    expect(rig.clock.timers).toHaveLength(0); // nothing is scheduled until the person starts something
  });

  it("WEB_8a_skills_render_no_console_error_or_warning_by_day_or_night", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const rig = await mountSkills();
    await rig.update(NIGHT);
    expect(error).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });
});

describe("WEB_8a_skills_render: the summary pills (README Skills 1)", () => {
  it("WEB_8a_skills_render_the_pills_of_the_sample_data_read_4_trusted_2_learning_6_need_your_help", async () => {
    const { el } = await mountSkills();
    for (const t of ["4 trusted", "2 learning", "6 need your help"]) {
      expect(elWithText(el, t), t).toBeDefined();
    }
    expect(pageText(el)).not.toContain("Nothing waiting");
  });

  it("WEB_8a_skills_render_the_pills_follow_the_Api_trusted_and_learning_by_st_and_help_is_questions_plus_reviews", async () => {
    // trusted by `st`: invoice, triage, calls; learning: fw; `starter` is live but "review" (counts in neither);
    // `log` is a draft. Questions saved up: the skills with an `ask` (invoice, starter); reviews: one.
    const list = ["invoice", "triage", "calls", "fw", "starter", "log"].map(skill);
    const api = skillsApi({
      getSkills: () => fixtureResult(list),
      getLearn: () => fixtureResult({ ...learn, reviews: learn.reviews.slice(0, 1) }),
    });
    const { el } = await mountSkills({ api });
    expect(elWithText(el, "3 trusted")).toBeDefined();
    expect(elWithText(el, "1 learning")).toBeDefined();
    expect(elWithText(el, "3 need your help")).toBeDefined();
    expect(elWithText(el, "6 skills")).toBeDefined();
  });

  it("WEB_8a_skills_render_with_nothing_to_answer_or_review_the_third_pill_says_Nothing_waiting", async () => {
    const list = ["triage", "calls", "fw", "log"].map(skill);
    const api = skillsApi({
      getSkills: () => fixtureResult(list),
      getLearn: () => fixtureResult({ ...learn, reviews: [] }),
    });
    const { el } = await mountSkills({ api });
    expect(elWithText(el, "2 trusted")).toBeDefined();
    expect(elWithText(el, "1 learning")).toBeDefined();
    expect(elWithText(el, "Nothing waiting")).toBeDefined();
    expect(pageText(el)).not.toContain("need your help");
    expect(elWithText(el, "4 skills")).toBeDefined();
  });

  it("STUDIO_4_skills_render_Teach_Tilo_a_skill_is_the_one_primary_button", async () => {
    const { el } = await mountSkills();
    const button = q(el, "button");
    expect(textOf(button)).toBe("+ Teach Tilo a skill");
    expect(qa(el, ".park-btn--primary")).toEqual([button]);
  });
});

// STUDIO-4: the 4-step Teach card and its pictures were replaced by the 3-step Teach wizard;
// its tests are in Skills.STUDIO_4.test.tsx.

describe("WEB_8a_skills_render: data comes through the Api, and shows only what it returned", () => {
  it("WEB_8a_skills_render_reads_the_skills_and_the_learn_data_and_nothing_it_does_not_need", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no network"));
    const api = skillsApi();
    const reads = new Set<string>();
    for (const name of [
      "getUser",
      "getToday",
      "getDecisions",
      "getWorlds",
      "getPlans",
      "getLedger",
      "getAgenda",
      "getTeam",
      "getConnectors",
      "getNotifications",
    ] as const) {
      const fn = api[name] as (...a: unknown[]) => Promise<unknown>;
      (api as unknown as Record<string, unknown>)[name] = (...a: unknown[]) => {
        reads.add(name);
        return fn(...a);
      };
    }
    await mountSkills({ api });
    expect(api.getSkills).toHaveBeenCalled();
    expect(api.getLearn).toHaveBeenCalled();
    expect(api.saveSkill).not.toHaveBeenCalled(); // nothing is written by looking
    expect([...reads].filter((n) => n !== "getUser" && n !== "getLedger")).toEqual([]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("WEB_8a_skills_render_while_loading_no_count_shows_but_the_root_is_there", async () => {
    const { el } = await mountSkills({ api: pendingApi() });
    expect(qa(el, '[data-testid="park-page-skills"]')).toHaveLength(1);
    expect(pageText(el)).not.toMatch(COUNT);
  });

  it("WEB_8a_skills_render_a_live_Api_that_is_not_built_says_Not_connected_yet_and_shows_no_count", async () => {
    const { el } = await mountSkills({ api: createLiveApi() });
    const text = pageText(el);
    expect(text).toContain("Skills data is unavailable");
    expect(text).not.toMatch(COUNT);
    expect(text).not.toMatch(/NotBuilt|not_built|getSkills|getLearn|undefined/);
    expect(qa(el, "h1")).toHaveLength(1);
  });

  it("WEB_8a_skills_render_when_either_read_fails_there_are_no_made_up_numbers", async () => {
    const skillsDown = await mountSkills({ api: skillsApi({ getSkills: rejects }) });
    // M2-ERRCOPY-1: an actual failed read is distinct from the NotBuilt control above.
    expect(pageText(skillsDown.el)).toContain("Skills could not load");
    expect(qa(skillsDown.el, "[data-api-read-state] button")).toHaveLength(1);
    expect(pageText(skillsDown.el)).not.toMatch(COUNT);
    expect(pageText(skillsDown.el)).not.toContain("offline-7f3");
    cleanup();
    // Without the learn data the "need your help" count cannot be known, so no count of it is shown.
    const learnDown = await mountSkills({ api: skillsApi({ getLearn: rejects }) });
    expect(pageText(learnDown.el)).toContain("Skills could not load");
    expect(qa(learnDown.el, "[data-api-read-state] button")).toHaveLength(1);
    expect(pageText(learnDown.el)).not.toMatch(/need your help|Nothing waiting/);
    expect(pageText(learnDown.el)).not.toContain("offline-7f3");
  });

  it("WEB_8a_skills_render_no_console_error_while_loading_or_not_built", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await mountSkills({ api: pendingApi() });
    cleanup();
    await mountSkills({ api: createLiveApi() });
    expect(error).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });
});
