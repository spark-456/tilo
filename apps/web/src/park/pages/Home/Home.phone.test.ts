import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../../test-support/park/componentsCss";

// UI-STUDIO-2: Home's phone block starts at 840px (the nav goes compact there); Worlds keeps 480px.
function phoneRule(file: string, selector: string, media = "@media (max-width: 480px)") {
  const css = readFileSync(join(__dirname, file), "utf8");
  const phone = css.slice(css.lastIndexOf(media));
  const rules = parseRules(phone).rules.filter((r) => r.selector === `[data-park] ${selector}`);
  return [{ decls: new Map(rules.flatMap((r) => [...r.decls])) }];
}

const HOME_PHONE = "@media (max-width: 840px)";

describe("M2-PHONE-1 small-screen controls", () => {
  it("uses one column for the confirm card so its actions cannot steal text width", () => {
    expect(
      phoneRule("Home.css", ".park-home-plan", HOME_PHONE)
        .at(-1)
        ?.decls.get("grid-template-columns"),
    ).toBe("minmax(0, 1fr)");
  });
  it.each([".park-home-run__link", ".park-home-run__edit input", ".park-home-change"])(
    "%s has a 44px minimum touch height",
    (selector) => {
      expect(phoneRule("Home.css", selector, HOME_PHONE).at(-1)?.decls.get("min-height")).toBe(
        "44px",
      );
    },
  );
  it("wraps long goals and assumptions instead of clipping them", () => {
    for (const selector of [".park-home-plan__query", ".park-home-step > span"]) {
      expect(phoneRule("Home.css", selector, HOME_PHONE).at(-1)?.decls.get("overflow-wrap")).toBe(
        "anywhere",
      );
    }
  });
  it.each([".park-worlds-dec__yes", ".park-worlds-dec__open"])(
    "Needs-you %s is a 44px target and wraps long action labels",
    (selector) => {
      const rule = phoneRule("../Worlds/Worlds.css", selector).at(-1);
      expect(rule?.decls.get("min-height")).toBe("44px");
      expect(rule?.decls.get("white-space")).toBe("normal");
    },
  );
});
