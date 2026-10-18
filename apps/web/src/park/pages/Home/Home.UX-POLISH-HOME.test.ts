import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "Home.css"), "utf8");

const block = (selector: string): string => {
  const start = css.indexOf(selector);
  expect(start, `missing ${selector}`).toBeGreaterThanOrEqual(0);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
};

describe("UX_POLISH_HOME", () => {
  it("UX_POLISH_HOME_styles_weekly_controls_instead_of_leaving_browser_defaults", () => {
    expect(block('[data-park] .park-home-repeat__toggle input[type="checkbox"]')).toContain(
      "appearance: none",
    );
    expect(css).toMatch(/\[data-park\] \.park-home-repeat__fields select \{[^}]*appearance: none/s);
  });

  it("UX_POLISH_HOME_uses_quiet_navigation_links_and_card_empty_states", () => {
    expect(block("[data-park] .park-home-link")).toContain("text-decoration: none");
    expect(block("[data-park] .park-home-none")).toContain("background: var(--sunk)");
  });
});
