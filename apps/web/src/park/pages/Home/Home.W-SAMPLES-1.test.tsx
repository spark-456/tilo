// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import suggestions from "../../../../../../config/home_suggestions.json";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  clickEl,
  control,
  mountHome,
  settle,
  taskInput,
} from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

it("W_SAMPLES_1_FR_UX_13_four_config_tasks_fill_the_composer_without_starting", async () => {
  const rig = await mountHome();
  expect(suggestions).toHaveLength(4);
  expect(rig.el.querySelectorAll(".park-home-chip")).toHaveLength(4);
  const draftTimers = rig.sch.timers.length;
  for (const suggestion of suggestions) {
    clickEl(control(rig.el, suggestion.label));
    await settle();
    expect(taskInput(rig.el).value).toBe(suggestion.prompt);
    expect(rig.sch.timers).toHaveLength(draftTimers);
    expect(rig.el.querySelector(".park-home-plan")).toBeNull();
  }
  expect(rig.navigate).not.toHaveBeenCalled();
  expect(vi.mocked(rig.app.addWorld)).not.toHaveBeenCalled();
});
