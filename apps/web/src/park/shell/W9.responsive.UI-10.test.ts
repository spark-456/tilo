import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";
import { rulesAtWidth } from "../../../test-support/park/pageCss";

function phoneRule(page: string, target: string) {
  const css = readFileSync(join(__dirname, `../pages/${page}/${page}.css`), "utf8");
  const selector = `[data-park] [data-testid="park-page-${page.toLowerCase()}"] .${target}`;
  const phone = rulesAtWidth(css, 320).find((rule) => rule.selector === selector);
  expect(rulesAtWidth(css, 1440).some((rule) => rule.selector.includes("data-testid"))).toBe(false);
  return phone?.decls;
}

it("UI_10_W9 CSS reader applies viewport ranges and preserves descendant selectors", () => {
  const css = `
    [data-park] .parent .child { color: red; }
    @media (min-width: 300px) and (max-width: 600px) {
      [data-park] .parent .child { min-height: 24px; }
    }`;
  expect(rulesAtWidth(css, 320).map((rule) => rule.selector)).toEqual([
    "[data-park] .parent .child",
    "[data-park] .parent .child",
  ]);
  for (const width of [299, 601, 1440]) {
    expect(rulesAtWidth(css, width)).toHaveLength(1);
    expect(rulesAtWidth(css, width)[0]?.decls.get("color")).toBe("red");
  }
});

it.each([
  ["Connectors", "park-connectors-grid"],
  ["Connectors", "park-connectors-availgrid"],
  ["Profile", "park-profile-form"],
])("UI_10_W9 %s %s has a shrinkable phone grid", (page, target) => {
  expect(phoneRule(page, target)?.get("grid-template-columns")).toBe("minmax(0, 1fr)");
});

it("UI_10_W9 Team coverage can fit a 320px phone without its desktop column minima", () => {
  expect(phoneRule("Team", "park-team-cover")?.get("grid-template-columns")).toBe("minmax(0, 1fr)");
  expect(phoneRule("Team", "park-team-matrix")?.get("overflow-x")).toBe("auto");
});

it("UI_10_W9 Connectors title count wraps within a 320px phone sheet", () => {
  expect(phoneRule("Connectors", "park-connectors-titlerow")?.get("flex-wrap")).toBe("wrap");
});

it("UI_10_W9 Agenda sync copy wraps and pin inputs shrink inside the phone board", () => {
  expect(phoneRule("Agenda", "park-agenda-synced")?.get("white-space")).toBe("normal");
  expect(phoneRule("Agenda", "park-agenda-newinput")?.get("min-width")).toBe("0");
  expect(phoneRule("Agenda", "park-agenda-newinput")?.get("box-sizing")).toBe("border-box");
});

it("UI_10_W9 Ledger chart labels have an opaque surface over dashed plot lines", () => {
  const rules = parseRules(
    readFileSync(join(__dirname, "../pages/Ledger/Ledger.css"), "utf8"),
  ).rules;
  for (const label of ["park-ledger-ylabel", "park-ledger-note"]) {
    const rule = rules.find((r) => r.selector === `[data-park] .${label}`);
    expect(rule?.decls.get("background")).toBe("var(--card)");
  }
});
