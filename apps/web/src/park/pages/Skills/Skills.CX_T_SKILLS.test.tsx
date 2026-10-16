// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, q } from "../../../../test-support/park/componentsHarness";
import { mountSkills, pageText } from "../../../../test-support/park/skillsHarness";

afterEach(cleanup);

describe("CX_T_SKILLS Skills board", () => {
  it("test_CX_T_SKILLS_keeps_how_to_guidance_and_existing_skill_library", async () => {
    const { el } = await mountSkills();
    const how = q(el, 'section[aria-label="How skills work"]');
    expect(pageText(how)).toContain("Tilo picks the right skill");
    expect(pageText(how)).toContain("Show it how, one time");
    expect(pageText(how)).toContain("Ratings make it better");
    expect(q(el, 'section[aria-label="All skills"]')).toBeTruthy();
  });
});
