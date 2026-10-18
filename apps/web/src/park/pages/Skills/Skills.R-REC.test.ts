import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { norm, parseRules } from "../../../../test-support/park/componentsCss";

it("R-REC contains the recording preview inside its card", () => {
  const css = readFileSync(join(__dirname, "SkillsStudio.css"), "utf8");
  const preview = parseRules(css).rules.find((rule) =>
    rule.selector.includes(".park-teach__drop video"),
  );

  expect(preview, "the recording preview needs a dedicated containment rule").toBeDefined();
  expect(norm(preview?.decls.get("aspect-ratio"))).toBe("16 / 9");
  expect(norm(preview?.decls.get("max-width"))).toBe("100%");
  expect(norm(preview?.decls.get("max-height"))).toBe("360px");
  expect(norm(preview?.decls.get("border-radius"))).toBe("16px");
});
