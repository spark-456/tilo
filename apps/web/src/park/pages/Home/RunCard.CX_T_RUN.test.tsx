// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import type { RunPlan } from "../../api/oneStep";
import { RunCard } from "./RunCard";

afterEach(cleanup);

const plan: RunPlan = {
  taskId: "t_1",
  goal: "Make a world",
  lines: [],
  approachId: "balanced",
  approachLabel: "Balanced",
  credits: { min: 2, max: 3 },
  cap: 3,
  usd: null,
  time: "a few minutes",
  makeChoices: [],
};

it("CX_T_RUN_card_folds_only_for_a_real_Start_click_not_other_busy_work", () => {
  const start = vi.fn();
  const render = (starting: boolean) =>
    mount(
      <RunCard
        plan={plan}
        busy
        starting={starting}
        error={null}
        onStart={start}
        onCancel={() => undefined}
        onEdit={() => undefined}
      />,
    );
  const editing = render(false);
  expect(editing.container.querySelector("[data-testid='run-card']")?.className).not.toContain(
    "starting",
  );
  editing.unmount();
  const started = render(true);
  expect(started.container.querySelector("[data-testid='run-card']")?.className).toContain(
    "starting",
  );
  expect(started.container.textContent).toContain("Starting your world");
});

it("CX_T_RUN_start_state_shows_a_blueprint_cue_only_after_Start", () => {
  const render = (starting: boolean) =>
    mount(
      <RunCard
        plan={plan}
        busy
        starting={starting}
        error={null}
        onStart={() => undefined}
        onCancel={() => undefined}
        onEdit={() => undefined}
      />,
    );
  const idle = render(false);
  expect(idle.container.querySelector("[data-testid='run-blueprint']")).toBeNull();
  idle.unmount();
  const started = render(true);
  expect(started.container.querySelector("[data-testid='run-blueprint']")?.textContent).toContain(
    plan.goal,
  );
});
