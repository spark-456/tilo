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

it("UI_10_W_AXE_1b_phone_tools_leave_room_for_the_whole_page_label", () => {
  const css = fs.readFileSync(path.join(__dirname, "park.shell.css"), "utf8");
  const phone = css.match(/@media \(max-width: 430px\) \{([\s\S]*?)\n\}/g)?.join("\n");
  expect(phone).toMatch(/\.park-shell__tools\s*\{\s*gap:\s*0;/);
});
