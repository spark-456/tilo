import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "Worlds.css"), "utf8");
const page = readFileSync(join(here, "WorldsPage.tsx"), "utf8");

const block = (selector: string): string => {
  const start = css.indexOf(selector);
  expect(start, `missing ${selector}`).toBeGreaterThanOrEqual(0);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
};

describe("UX_POLISH_WORLDS", () => {
  it("UX_POLISH_WORLDS_replaces_browser_select_arrows_with_a_consistent_control", () => {
    expect(block("[data-park] .park-worlds-slackselect {")).toContain("appearance: none");
    expect(page.match(/className="park-worlds-slackselectwrap"/g)).toHaveLength(2);
    expect(block("[data-park] .park-worlds-slackselectwrap::after")).toContain('content: "⌄"');
  });

  it("UX_POLISH_WORLDS_uses_quiet_links_and_a_calm_routine_empty_card", () => {
    expect(block("[data-park] .park-worlds-routines a {")).toContain("text-decoration: none");
    expect(block("[data-park] .park-worlds-routine-empty")).toContain("background: var(--sunk)");
  });
});
