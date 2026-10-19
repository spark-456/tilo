// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountHome } from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

it("FR_UX_13_COMPOSER_1_unavailable_intake_renders_no_clutter_and_keeps_task_controls", async () => {
  const rig = await mountHome();
  const text = rig.el.textContent ?? "";
  expect(text).not.toContain("Add anything");
  expect(text).not.toContain("Task and sources");
  expect(text).not.toContain("File intake is not available yet");
  expect(text).not.toContain("Start a real task");
  expect(rig.el.querySelector('[aria-label="Describe your task"]')).not.toBeNull();
  expect(text).toContain("Start task");
  expect(text).toContain("Quick task");
  expect(text).toContain("Routine");
  expect(text).toContain("Workspace");
  expect(text).toContain("You see the plan and the cost before any agent starts.");
});
