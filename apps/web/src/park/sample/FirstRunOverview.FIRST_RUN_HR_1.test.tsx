// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, q } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { worlds } from "../api/fixtures/worlds";
import type { World } from "../api/types";
import { useApp } from "../app/context";
import { HomePage } from "../pages/Home/HomePage";
import { WorldsPage } from "../pages/Worlds/WorldsPage";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);
afterEach(cleanup);
const personal = { ...worlds()[0], id: "personal", sample: false } as World;
function Both() {
  const app = useApp();
  return (
    <>
      <HomePage app={app} />
      <WorldsPage app={app} />
    </>
  );
}
async function setup(owned = false) {
  const api = liveApi();
  api.getWorlds = vi.fn(async () => ({ data: owned ? [personal] : [], source: "live" as const }));
  api.startWorld = vi.fn(async () => ({
    data: { ok: true as const, world: personal },
    source: "live" as const,
  }));
  for (const name of ["startWorld", "decide", "undo", "setPref", "saveSkill"] as const)
    vi.spyOn(api, name);
  const node = mountShell(<Both />, { api });
  await settle();
  return { api, node };
}
it("FIRST_RUN_HR_1_home_worlds_previews_are_labelled_read_only_and_keep_real_controls", async () => {
  const { api, node } = await setup();
  const home = q(node.m.container, '[data-first-run-overview="home"]');
  for (const title of ["Needs you", "Live now", "Up next", "Spend"])
    expect(home.textContent).toContain(title);
  const world = q(node.m.container, '[data-first-run-overview="worlds"]');
  for (const tier of ["City", "Town", "Village"]) expect(world.textContent).toContain(tier);
  for (const panel of node.m.container.querySelectorAll(
    "[data-first-run-overview] .park-first-run-card",
  ))
    expect(panel.textContent).toContain("Sample");
  expect(node.m.container.querySelector('[aria-label="Describe your task"]')).not.toBeNull();
  expect(node.m.container.textContent).toContain("Show sample project");
  // JUDGE-FIRST-RUN F2/F3: the first-task buttons only fill the task box and the two "recorded project" buttons only
  // open the read-only sample (both covered in FirstTask.JUDGE_FIRST_RUN.test.tsx); every other button explains.
  for (const button of node.m.container.querySelectorAll(
    "[data-first-run-overview] button.park-first-run-explain",
  ))
    if (button.textContent !== "Open the recorded sample project") click(button);
  expect(seen.store.getState().toast?.message).toContain("sample data");
  for (const name of ["startWorld", "decide", "undo", "setPref", "saveSkill"] as const)
    expect(api[name]).not.toHaveBeenCalled();
  expect(node.navigate).not.toHaveBeenCalled();
});
it("FIRST_RUN_HR_1_real_start_removes_home_worlds_previews_on_next_render", async () => {
  const { node } = await setup();
  expect(node.m.container.querySelectorAll("[data-first-run-overview]")).toHaveLength(2);
  await act(async () => {
    expect(await seen.store.startWorld("workspace", "Personal task")).toBe(true);
  });
  expect(node.m.container.querySelector("[data-first-run-overview]")).toBeNull();
  expect(node.m.container.querySelector('[aria-label="Describe your task"]')).not.toBeNull();
});
it("FIRST_RUN_HR_1_existing_personal_world_never_gets_home_worlds_previews", async () => {
  const { node } = await setup(true);
  expect(node.m.container.querySelector("[data-first-run-overview]")).toBeNull();
});
