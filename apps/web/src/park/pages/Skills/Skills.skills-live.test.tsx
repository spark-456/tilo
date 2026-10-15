// @vitest-environment happy-dom
// SKILLS-LIVE (HR-1, PRD 9.4): "Who helped this month" on a live page shows only what the page has loaded. The sample
// numbers (Mistakes since July -38%, 41 answers and fixes, September, the sample helpers) stay in sample mode; a live
// page with nothing served says "No answers or fixes yet this month", names the current month from the clock, and does
// not count an answer given on the page as saved (no route saves it).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  type SkillsRig,
  clickEl,
  control,
  elWithText,
  mountSkills,
  pageText,
  settle,
  skillsApi,
  toasts,
} from "../../../../test-support/park/skillsHarness";
import { HELPER_SUMMARY_FIXTURE } from "../../api/index";
import { type SkillRow, skillFromRow } from "../../api/live/skillsFromApi";
import type { Learn, Skill } from "../../api/types";
import { currentMonthLabel } from "./HelpSection";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const ASKING: SkillRow = {
  id: "tsk_Q1",
  name: "Match invoices",
  scope: { kind: "just_me", team: null },
  status: "learning",
  paused: false,
  plan: [{ text: "Read the mail", tool: "gmail", action: "read_email", ask_first: false }],
  question: { text: "Link or PDF?", options: ["Open the link", "Skip"], answer: null },
};
const NO_LEARN: Learn = { rates: [], reviews: [], helpers: [], tools: [] };

async function live(skills: Skill[] = [], learn: Learn = NO_LEARN): Promise<SkillsRig> {
  const api = skillsApi({
    getSkills: async () => ({ data: skills, source: "live" }),
    getLearn: async () => ({ data: learn, source: "live" }),
  });
  return mountSkills({ api });
}
const whoCard = (r: SkillsRig): string => {
  const head = elWithText(r.el, "Who helped this month");
  const card = head?.closest(".park-skills-help-card");
  if (!card) throw new Error("no Who helped card");
  return pageText(card);
};

describe("SKILLS_LIVE: Who helped this month on a live page", () => {
  it("SKILLS_LIVE_shows_an_honest_empty_state_and_no_sample_number", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-15T09:15:00Z"));
    const r = await live();
    const card = whoCard(r);
    expect(card).toContain("No answers or fixes yet this month");
    expect(card).toContain("October");
    for (const sample of [
      "Mistakes since July",
      HELPER_SUMMARY_FIXTURE.mistakesDeltaSinceJuly,
      String(HELPER_SUMMARY_FIXTURE.baseMonthlyAnswersAndFixes),
      HELPER_SUMMARY_FIXTURE.helperMonthLabel,
    ])
      expect(card, sample).not.toContain(sample);
  });

  it("SKILLS_LIVE_counts_only_the_helpers_the_server_served", async () => {
    const helpers: Learn["helpers"] = [
      { id: "p1", name: "Priya", init: "P", c: "#888", impact: "2 fixes", n: 2 },
      { id: "p2", name: "Sam", init: "S", c: "#777", impact: "1 answer", n: 1 },
    ];
    const r = await live([], { ...NO_LEARN, helpers });
    const card = whoCard(r);
    expect(card).toContain("Answers and fixes3");
    expect(card).not.toContain("Mistakes since July");
    expect(card).not.toContain("No answers or fixes yet");
  });

  it("SKILLS_LIVE_an_answer_on_the_page_is_not_counted_or_claimed_as_saved", async () => {
    const r = await live([skillFromRow(ASKING)]);
    clickEl(control(r.el, "Open the link"));
    await settle();
    expect(whoCard(r)).toContain("No answers or fixes yet this month");
    expect(pageText(r.el)).toContain("noted on this page only");
    expect(pageText(r.el)).not.toContain("every agent now knows");
    expect(toasts(r.app).flat().join(" ")).toContain("Noted on this page only");
    expect(toasts(r.app).flat().join(" ")).not.toContain("now knows");
  });

  it("SKILLS_LIVE_the_month_label_comes_from_the_clock", () => {
    expect(currentMonthLabel(new Date("2026-01-20T12:00:00Z"))).toBe("January");
    expect(currentMonthLabel(new Date("2026-12-02T12:00:00Z"))).toBe("December");
  });
});

describe("SKILLS_LIVE: sample mode keeps its sample numbers", () => {
  it("SKILLS_LIVE_the_fixture_page_still_shows_the_designed_summary", async () => {
    const r = await mountSkills({ api: skillsApi() });
    const card = whoCard(r);
    expect(card).toContain("Mistakes since July");
    expect(card).toContain(HELPER_SUMMARY_FIXTURE.mistakesDeltaSinceJuly);
    expect(card).toContain(HELPER_SUMMARY_FIXTURE.helperMonthLabel);
  });
});
