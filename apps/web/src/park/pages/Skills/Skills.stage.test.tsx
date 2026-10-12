// @vitest-environment happy-dom
// FR-UX-12 phone pass: the Skills page draws itself in three parts (header and Teach card, then "Help your agents
// get better", then "Learned skills"), one task each, so mounting the tab holds the thread for less (the tab mount
// was a 219 ms long task at 4x CPU). Parts are only ever added below what is on screen. Without a CSS animation
// engine (the DOM stand-in) every part is drawn at the first render, as before.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, qa } from "../../../../test-support/park/componentsHarness";
import { mountSkills } from "../../../../test-support/park/skillsHarness";

const g = globalThis as unknown as { CSSAnimation?: unknown };
const had = "CSSAnimation" in g;
afterEach(() => {
  if (!had) Reflect.deleteProperty(g, "CSSAnimation");
  cleanup();
});

const sections = (el: HTMLElement) =>
  qa(el, "section.park-skills-section").map((s) => s.getAttribute("aria-label"));

describe("FR_UX_12 Skills draws in parts", () => {
  it("FR_UX_12_skills_parts_follow_each_other: only the card at first; the help section and the library follow, added below", async () => {
    g.CSSAnimation = class {};
    const { el, clock } = await mountSkills();
    const first = sections(el);
    expect(first).not.toContain("Help your agents get better");
    expect(first).not.toContain("Learned skills");
    expect(qa(el, "h1")).toHaveLength(1);
    // the fake clock runs each part's task, including the ones a firing task schedules
    clock.advance(0);
    expect(sections(el)).toEqual(["Help your agents get better", "Learned skills"]);
  });

  it("FR_UX_12_skills_all_drawn_without_css_animations: the DOM stand-in draws every part at the first render", async () => {
    const { el } = await mountSkills();
    expect(sections(el)).toEqual(["Help your agents get better", "Learned skills"]);
  });
});
