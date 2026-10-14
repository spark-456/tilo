import fs from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";

it("UI_10_W_AXE_1_sample_hit_area_cannot_shrink_below_24px", () => {
  const css = fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");
  const rule = css.match(/\[data-park\] \.park-shell__sample \{([^}]+)\}/)?.[1];
  expect(rule).toMatch(/min-width:\s*24px/);
  expect(rule).toMatch(/min-height:\s*24px/);
  expect(rule).toMatch(/flex-shrink:\s*0/);
});
