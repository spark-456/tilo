import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { parseRules } from "../../../../test-support/park/componentsCss";

function phoneRule(file: string, selector: string) {
  const css = readFileSync(join(__dirname, file), "utf8");
  const phone = css.slice(css.lastIndexOf("@media (max-width: 480px)"));
  const rules = parseRules(phone).rules.filter((r) => r.selector === `[data-park] ${selector}`);
  return [{ decls: new Map(rules.flatMap((r) => [...r.decls])) }];
}

describe("M2-PHONE-1 small-screen controls", () => {
  it("uses one column for the confirm card so its actions cannot steal text width", () => {
    expect(
      phoneRule("Home.css", ".park-home-plan").at(-1)?.decls.get("grid-template-columns"),
    ).toBe("minmax(0, 1fr)");
  });
  it.each([".park-home-run__link", ".park-home-run__edit input", ".park-home-change"])(
    "%s has a 44px minimum touch height",
    (selector) => {
      expect(phoneRule("Home.css", selector).at(-1)?.decls.get("min-height")).toBe("44px");
    },
  );
  it("wraps long goals and assumptions instead of clipping them", () => {
    for (const selector of [".park-home-plan__query", ".park-home-step > span"]) {
      expect(phoneRule("Home.css", selector).at(-1)?.decls.get("overflow-wrap")).toBe("anywhere");
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
