// @vitest-environment happy-dom
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { parseRules } from "../../../test-support/park/componentsCss";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { SampleChip } from "./SampleChip";

afterEach(cleanup);
const rules = parseRules(fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8")).rules;

describe("UI_10_W14 header and splash", () => {
  it("UI_10_W14 the compact sample control has a named information icon", () => {
    const m = mount(<SampleChip />);
    const button = m.container.querySelector("button");
    const label = document.getElementById(button?.getAttribute("aria-labelledby") ?? "");
    expect(label?.textContent).toBe("Sample data");
    expect(button?.querySelector("svg")).not.toBeNull();
  });

  it("UI_10_W14 sample target never borrows space from neighbouring controls", () => {
    const sample = rules.filter((r) => r.selector === "[data-park] .park-shell__sample");
    for (const rule of sample) {
      expect(rule.decls.get("margin") ?? "0").not.toMatch(/-\d/);
    }
    expect(sample.some((r) => r.decls.get("min-width") === "24px")).toBe(true);
    expect(sample.some((r) => r.decls.get("min-height") === "24px")).toBe(true);
  });

  it("UI_10_W14 the fading splash hides all loading artwork once the UI paints", () => {
    expect(
      rules.some(
        (r) =>
          r.selector === "[data-park] .park-shell__boot--out > *" &&
          r.decls.get("visibility") === "hidden",
      ),
    ).toBe(true);
  });
});
