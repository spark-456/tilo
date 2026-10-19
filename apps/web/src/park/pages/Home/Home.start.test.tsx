// @vitest-environment happy-dom
// RETIRE-OLD-APP phase 0: the Home composer no longer links to the old intake.
// The task input, start control, drafting and plan remain available.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, qa } from "../../../../test-support/park/componentsHarness";
import { MODES } from "../../../../test-support/park/homeCopy";
import {
  clickEl,
  control,
  goCalls,
  hasControl,
  mountHome,
  taskInput,
  textOf,
  typeInto,
} from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

const LABEL = "Start a real task";
const links = (el: HTMLElement) =>
  qa<HTMLAnchorElement>(el, "a").filter((a) => textOf(a) === LABEL);

describe("RETIRE_OLD_APP_home_start", () => {
  it("RETIRE_OLD_APP_home_has_no_old_intake_link_or_navigation", async () => {
    const rig = await mountHome();
    const found = links(rig.el);
    expect(found).toHaveLength(0);
    expect(qa(rig.el, 'a[href="/start"]')).toHaveLength(0);
    expect(goCalls(rig.app)).toBe(0);
    expect(rig.navigate).not.toHaveBeenCalled();
  });

  it("WEB_CUTOVER_home_start_the_fixture_composer_is_unchanged_beside_it", async () => {
    const rig = await mountHome();
    expect(taskInput(rig.el).placeholder).toMatch(/^e\.g\. /);
    expect(hasControl(rig.el, MODES[0]?.start ?? "")).toBe(true);
    expect(links(rig.el)).toHaveLength(0);
  });

  it("RETIRE_OLD_APP_home_old_link_stays_absent_through_drafting_and_plan", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Plan a launch");
    clickEl(control(rig.el, MODES[0]?.start ?? ""));
    expect(links(rig.el)).toHaveLength(0);
    rig.sch.fire(rig.sch.live().filter((t) => t.ms === 900)[0]);
    expect(links(rig.el)).toHaveLength(0);
  });
});
