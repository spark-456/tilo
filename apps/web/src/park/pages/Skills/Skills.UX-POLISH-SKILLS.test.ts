import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const cssSkills = readFileSync(join(here, "Skills.css"), "utf8");
const cssStudio = readFileSync(join(here, "SkillsStudio.css"), "utf8");
const allCss = `${cssSkills}\n${cssStudio}`;

const block = (css: string, selector: string): string => {
  const start = css.indexOf(selector);
  expect(start, `missing ${selector}`).toBeGreaterThanOrEqual(0);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
};

describe("UX_POLISH_SKILLS", () => {
  it("UX_POLISH_SKILLS_styles_tool_access_and_fix_selects_consistently_with_no_raw_arrows", () => {
    expect(block(allCss, "[data-park] .park-skills-access-select {")).toContain("appearance: none");
    expect(block(allCss, "[data-park] .park-skills-access-selectwrap::after {")).toContain(
      'content: "⌄"',
    );
    expect(block(allCss, "[data-park] .park-skills-fix-select {")).toContain("appearance: none");
    expect(block(allCss, "[data-park] .park-skills-fix-selectwrap::after {")).toContain(
      'content: "⌄"',
    );
  });

  it("UX_POLISH_SKILLS_styles_checkbox_controls_instead_of_leaving_browser_defaults", () => {
    expect(
      block(allCss, '[data-park] .park-teach__checkbox-label input[type="checkbox"] {'),
    ).toContain("appearance: none");
    expect(
      block(allCss, '[data-park] .park-skills-fix-checkbox-label input[type="checkbox"] {'),
    ).toContain("appearance: none");
  });

  it("UX_POLISH_SKILLS_uses_quiet_links_without_blue_underlines", () => {
    expect(block(allCss, "[data-park] .park-skill-link {")).toContain("text-decoration: none");
    expect(block(allCss, "[data-park] .park-teach__setup-link {")).toContain(
      "text-decoration: none",
    );
  });

  it("UX_POLISH_SKILLS_uses_calm_card_empty_states", () => {
    expect(block(allCss, "[data-park] .park-skills-gallery__none {")).toContain(
      "background: var(--sunk)",
    );
    expect(block(allCss, "[data-park] .park-skills-who-empty {")).toContain(
      "background: var(--sunk)",
    );
    expect(block(allCss, "[data-park] .park-skills-drawer__empty {")).toContain(
      "background: var(--sunk)",
    );
  });
});
