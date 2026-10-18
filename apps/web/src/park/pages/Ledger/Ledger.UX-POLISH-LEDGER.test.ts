import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "Ledger.css"), "utf8");
const page = readFileSync(join(here, "LedgerPage.tsx"), "utf8");
const sections = readFileSync(join(here, "Sections.tsx"), "utf8");

const block = (selector: string): string => {
  const start = css.indexOf(selector);
  expect(start, `missing selector ${selector}`).toBeGreaterThanOrEqual(0);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
};

describe("UX_POLISH_LEDGER", () => {
  it("UX_POLISH_LEDGER_quiets_underlined_method_links_and_standardizes_page_links", () => {
    const methodBlock = block("[data-park] .park-ledger-method {");
    expect(methodBlock).toContain("text-decoration: none");
    expect(methodBlock).not.toContain("text-decoration: underline");

    const linkBlock = block("[data-park] .park-ledger-root a {");
    expect(linkBlock).toContain("text-decoration: none");
  });

  it("UX_POLISH_LEDGER_styles_empty_and_not_connected_states_as_calm_sunken_cards", () => {
    const emptyBlock = block("[data-park] .park-ledger-empty {");
    expect(emptyBlock).toContain("background: var(--sunk)");
    expect(emptyBlock).toContain("border: 1px solid var(--line2)");
    expect(emptyBlock).toContain("border-radius: 14px");

    const stateBlock = block("[data-park] .park-ledger-state {");
    expect(stateBlock).toContain("background: var(--sunk)");
    expect(stateBlock).toContain("border: 1px solid var(--line2)");
  });

  it("UX_POLISH_LEDGER_uses_park_ledger_empty_for_recorded_runs_and_chart_fallback", () => {
    expect(sections).toContain('className="park-ledger-empty"');
    expect(page).toContain('className="park-ledger-empty"');
  });
});
