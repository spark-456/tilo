// @vitest-environment happy-dom
// WEB-W3 (issue 932): an empty Start says the plan is an example; disabled live-view links are dimmed.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, expect, it } from "vitest";
import { cleanup, q } from "../../../../test-support/park/componentsHarness";
import { clickEl, mountHome, settle } from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

it("FR_UX_13_W3_an_empty_box_start_says_the_plan_is_only_an_example", async () => {
  const rig = await mountHome();
  clickEl(q(rig.el, "button.park-home-start"));
  await settle();
  for (const t of rig.sch.live().filter((x) => x.ms === 900)) rig.sch.fire(t); // the draft timer
  await settle();
  expect(rig.el.textContent).toContain("Example only: the box is empty.");
});

it("FR_UX_13_W3_disabled_live_view_and_lens_links_are_dimmed", () => {
  const css = readFileSync(join(process.cwd(), "src/park/pages/World/World.css"), "utf8");
  const rule = (sel: string) => css.slice(css.indexOf(sel), css.indexOf("}", css.indexOf(sel)));
  expect(rule('.park-world-live[aria-disabled="true"] {')).toMatch(/opacity: 0\.55/);
  expect(rule('.park-world-lenses a[aria-disabled="true"] {')).toMatch(/opacity: 0\.55/);
});
