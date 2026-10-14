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
import {
  CAPTURED_HINT,
  CARD_SUB,
  CARD_TITLE,
  DEFAULT_NAME,
  INTRO,
  METHODS,
  NO_STEPS_YET,
  SCREEN,
  STEP_LABELS,
} from "../../../../test-support/park/skillsCopy";
import {
  NIGHT,
  agentArt,
  artIn,
  control,
  currentStep,
  elWithText,
  fixtureResult,
  flat,
  goCalls,
  isDisabled,
  isOn,
  methodTile,
  mountSkills,
  pageText,
  pendingApi,
  pickedCount,
  reachable,
  rejects,
  skillNameField,
  skillsApi,
  stepBar,
  stepButtons,
  teachCard,
  textOf,
  toasts,
} from "../../../../test-support/park/skillsHarness";
import { learn, skills } from "../../api/fixtures";
import { createLiveApi } from "../../api/liveApi";
import type { Skill } from "../../api/types";

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
      expect(qa(el, ".park-sheet")).toHaveLength(1);
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
    expect(follows(h1, pill)).toBe(true);
    expect(textOf(button)).toBe("Teach a skill"); // the first control on the page
    expect(follows(pill, button)).toBe(true);
    expect(follows(button, teachCard(el))).toBe(true);
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

  it("WEB_8a_skills_render_Teach_a_skill_is_a_button_with_a_plus_icon", async () => {
    const { el } = await mountSkills();
    const button = q(el, "button");
    expect(textOf(button)).toBe("Teach a skill");
    expect(button.querySelector("svg")).not.toBeNull();
  });
});

describe("WEB_8a_skills_render: the Teach card, as first drawn (README Skills 2)", () => {
  it("WEB_8a_skills_render_the_card_is_a_labelled_region_with_its_title_and_line", async () => {
    const { el } = await mountSkills();
    const card = teachCard(el);
    expect(card.tagName === "SECTION" || card.getAttribute("role") === "region").toBe(true);
    expect(textOf(q(card, "h2"))).toBe(CARD_TITLE);
    expect(elWithText(card, CARD_SUB)).toBeDefined();
  });

  it("WEB_8a_skills_render_the_card_is_open_on_the_first_step_with_nothing_to_unfold", async () => {
    // The reference has no closed state: the card is the open card and "Teach a skill" scrolls to it.
    const { el } = await mountSkills();
    for (const m of METHODS) expect(methodTile(el, m.name)).toBeDefined();
    expect(currentStep(el)).toBe("Show it");
  });

  it("WEB_8a_skills_render_the_step_bar_is_a_labelled_ordered_list_of_four_numbered_steps", async () => {
    const { el } = await mountSkills();
    const items = qa(stepBar(el), "li");
    expect(stepBar(el).tagName).toBe("OL");
    expect(items.map((li) => flat(textOf(li)))).toEqual(
      STEP_LABELS.map((l, i) => flat(`${i + 1}${l}`)),
    );
    expect(stepButtons(el)).toHaveLength(4);
  });

  it("WEB_8a_skills_render_at_first_only_Show_it_can_be_pressed_and_it_is_the_current_step", async () => {
    const { el } = await mountSkills();
    expect(reachable(el)).toEqual([true, false, false, false]);
    expect(currentStep(el)).toBe("Show it");
    expect(qa(stepBar(el), '[aria-current="step"]')).toHaveLength(1);
  });

  it.each(METHODS.map((m) => [m.name, m.desc] as const))(
    "WEB_8a_skills_render_method_tile_%s_with_its_line",
    async (name, desc) => {
      const { el } = await mountSkills();
      expect(flat(textOf(methodTile(el, name)))).toBe(flat(`${name}${desc}`));
    },
  );

  it("WEB_8a_skills_render_Record_my_screen_is_the_chosen_method_and_the_others_are_not", async () => {
    const { el } = await mountSkills();
    const on = METHODS.map((m) => isOn(methodTile(el, m.name)));
    expect(on).toEqual([true, false, false, false]);
  });

  it("WEB_8a_skills_render_the_mock_browser_shows_the_address_the_hint_and_Start_recording", async () => {
    const { el } = await mountSkills();
    const card = teachCard(el);
    expect(elWithText(card, SCREEN.record.url)).toBeDefined();
    expect(elWithText(card, SCREEN.record.hint)).toBeDefined();
    expect(isDisabled(control(card, SCREEN.record.start))).toBe(false);
    expect(pageText(card)).not.toMatch(/REC 00:/);
  });

  it("WEB_8a_skills_render_what_Tilo_has_picked_up_starts_empty_with_the_name_and_a_disabled_next", async () => {
    const { el } = await mountSkills();
    const card = teachCard(el);
    expect(elWithText(card, "What Tilo has picked up")).toBeDefined();
    expect(pickedCount(el)).toBe(0);
    expect(elWithText(card, NO_STEPS_YET)).toBeDefined();
    expect(pageText(card)).not.toContain(CAPTURED_HINT);
    expect(skillNameField(el).value).toBe(DEFAULT_NAME);
    expect(isDisabled(control(card, "Show me Tilo’s version"))).toBe(true);
  });

  it("WEB_8a_skills_render_the_labelled_regions_of_the_inventory_are_there", async () => {
    // inventory.md: Teach a skill · Steps · (Describe the task, once Describe it is chosen) · Skill name
    const { el } = await mountSkills();
    expect(qa(el, '[aria-label="Teach a skill"]')).toHaveLength(1);
    expect(qa(el, '[aria-label="Steps"]')).toHaveLength(1);
    expect(qa(el, 'input[aria-label="Skill name"]')).toHaveLength(1);
  });

  it("WEB_8a_skills_render_every_control_has_a_name_and_every_button_is_type_button", async () => {
    const { el } = await mountSkills();
    for (const b of qa<HTMLButtonElement>(el, "button")) {
      expect(b.getAttribute("type"), textOf(b)).toBe("button");
      expect(
        (b.getAttribute("aria-label") ?? textOf(b)).length,
        "a button without a name",
      ).toBeGreaterThan(0);
    }
    for (const f of qa<HTMLInputElement>(el, "input, textarea")) {
      const named = f.getAttribute("aria-label") || f.closest("label")?.textContent?.trim();
      expect(named, "a field without a name").toBeTruthy();
    }
  });
});

describe("WEB_8a_skills_render: the pictures are the kit's own (design: K.agent)", () => {
  it("WEB_8a_skills_render_the_teacher_in_the_card_header_is_the_research_lead_talking", async () => {
    const { el } = await mountSkills();
    expect(await artIn(teachCard(el))).toContain(
      await agentArt({ role: "research", rank: "lead", expr: "talking" }, 58),
    );
  });

  it("WEB_8a_skills_render_by_night_the_pictures_are_drawn_for_night", async () => {
    const spec = { role: "research", rank: "lead", expr: "talking" };
    const night = await agentArt(spec, 58, true);
    const day = await agentArt(spec, 58, false);
    expect(night, "the kit draws night differently").not.toBe(day);
    const rig = await mountSkills({ app: NIGHT });
    expect(await artIn(teachCard(rig.el))).toContain(night);
    expect(await artIn(teachCard(rig.el))).not.toContain(day);
  });

  it("WEB_8a_skills_render_the_empty_list_of_steps_has_the_research_agent_waiting_neutral", async () => {
    const { el } = await mountSkills();
    expect(await artIn(teachCard(el))).toContain(
      await agentArt({ role: "research", expr: "neutral" }, 58),
    );
  });
});

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
