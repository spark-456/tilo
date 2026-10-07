// @vitest-environment happy-dom
// WEB-CUTOVER acceptance: "Start a real task" on Home. The composer is fixture-only until FR-UX-13 wires it to
// live intake, so the page links to the old app's intake form at /start (docs/park-designed-not-in-prd/
// Home.md). A plain link: a full navigation into the old app, never `app.go`, in every composer phase.
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

describe("WEB_CUTOVER_home_start: the way to a real task", () => {
  it("WEB_CUTOVER_home_start_a_real_task_link_points_at_the_intake", async () => {
    const rig = await mountHome();
    const found = links(rig.el);
    expect(found).toHaveLength(1);
    expect(found[0]?.getAttribute("href")).toBe("/start");
    expect(found[0]?.getAttribute("target")).toBeNull();
  });

  it("WEB_CUTOVER_home_start_a_real_task_is_a_full_navigation_not_app_go", async () => {
    const rig = await mountHome();
    const link = control(rig.el, LABEL);
    clickEl(link); // happy-dom does not navigate; the page must not intercept the click
    expect(goCalls(rig.app)).toBe(0);
    expect(rig.navigate).not.toHaveBeenCalled();
  });

  it("WEB_CUTOVER_home_start_the_fixture_composer_is_unchanged_beside_it", async () => {
    const rig = await mountHome();
    expect(taskInput(rig.el).placeholder).toMatch(/^e\.g\. /);
    expect(hasControl(rig.el, MODES[0]?.start ?? "")).toBe(true);
    // one entry, in plain words: no urgency, no badge
    expect(links(rig.el)).toHaveLength(1);
    expect(textOf(links(rig.el)[0] as HTMLElement)).toBe(LABEL);
  });

  it("WEB_CUTOVER_home_start_the_link_stays_through_drafting_and_the_plan", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Plan a launch");
    clickEl(control(rig.el, MODES[0]?.start ?? ""));
    expect(links(rig.el)).toHaveLength(1);
    rig.sch.fire(rig.sch.live().filter((t) => t.ms === 900)[0]);
    expect(links(rig.el)).toHaveLength(1);
  });
});
