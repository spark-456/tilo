// @vitest-environment happy-dom
// P0-SKILLS-PAGE:
// 1. Skills page layout: "Teach Tilo a skill" hero card responsive grid:
//    steps as 3 equal cards under the heading, CTA right, no clipped text at 800/1024/1440/390.
// 2. REMOVE the bottom pill everywhere for approvals:
//    "Waiting for your approval . 7 worlds" bottom pill removed; approvals live only in Needs you and the nav badge.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import { mountSkills, pageText } from "../../../../test-support/park/skillsHarness";
import type { World } from "../../api/types";
import { runBarOf } from "../../shell/runStatus";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const world = (over: Partial<World> = {}): World => ({
  id: "w-p0",
  name: "Approval world",
  short: "Approval world",
  tier: "Village",
  tool: "Quick task",
  st: "needs",
  agents: 0,
  spend: "",
  spendV: 0,
  nextL: "",
  nextV: "",
  owner: "",
  started: "",
  ...over,
});

describe("P0-SKILLS-PAGE: Teach Tilo hero card layout", () => {
  it("test_P0_SKILLS_PAGE_hero_card_has_steps_under_heading_and_cta_right", async () => {
    const { el } = await mountSkills();
    const banner = q(el, 'section[aria-label="Teach Tilo a skill"]');
    expect(banner, "hero banner missing").toBeTruthy();

    // CTA button is placed in the header area on the right
    const cta = q(banner, ".park-skills-banner__cta button") ?? q(banner, "button");
    expect(cta?.textContent?.trim()).toContain("Start teaching");

    // The heading and eyebrow
    expect(pageText(banner)).toContain("TEACH TILO A SKILL");
    expect(pageText(banner)).toContain("Show Tilo how you like it done, once.");

    // The 3 steps list must be rendered under the heading (direct child of banner or separate from the text block)
    const ways = q(banner, ".park-skills-banner__ways");
    expect(ways, "steps list missing").toBeTruthy();
    const textBlock = q(banner, ".park-skills-banner__text");
    expect(textBlock?.contains(ways), "steps must not be crushed inside the text column").toBe(
      false,
    );

    // 3 equal cards with numbers and complete captions
    const cards = qa(ways, "li");
    expect(cards).toHaveLength(3);

    const expectedSteps = [
      { n: "1", label: "Describe it", sub: "Write it in plain words" },
      { n: "2", label: "Show an example", sub: "What goes in, what comes out" },
      { n: "3", label: "Review the steps", sub: "Choose where Tilo asks first" },
    ];

    cards.forEach((card, i) => {
      const exp = expectedSteps[i];
      expect(exp).toBeDefined();
      if (!exp) return;
      expect(q(card, ".park-skills-banner__n")?.textContent?.trim()).toBe(exp.n);
      expect(pageText(card)).toContain(exp.label);
      expect(pageText(card)).toContain(exp.sub);
    });
  });
});

describe("P0-SKILLS-PAGE: bottom pill removed everywhere for approvals", () => {
  it("test_P0_SKILLS_PAGE_held_runs_do_not_produce_a_bottom_pill", () => {
    // Single needs world: must return null (no bottom pill for approvals)
    expect(runBarOf([world({ st: "needs" })])).toBeNull();

    // Multiple needs worlds (e.g. 7 worlds waiting for approval): must return null
    const sevenHeld = Array.from({ length: 7 }, (_, i) => world({ id: `w-${i}`, st: "needs" }));
    expect(runBarOf(sevenHeld)).toBeNull();
  });

  it("test_P0_SKILLS_PAGE_running_worlds_still_show_running_indicator_alone", () => {
    // When a world is running, running indicator works
    const running = world({ id: "w-run", st: "running", agents: 3 });
    const held = world({ id: "w-held", st: "needs" });
    const bar = runBarOf([running, held]);
    expect(bar?.kind).toBe("running");
    expect(bar?.label).toBe("3 agents working");
    expect(bar?.detail).toBe("Approval world");
  });
});
