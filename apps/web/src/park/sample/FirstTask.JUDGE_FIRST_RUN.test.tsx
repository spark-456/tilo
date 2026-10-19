// @vitest-environment happy-dom
// JUDGE-FIRST-RUN F2 and F3: a first visit offers one real thing to do (three example tasks that fill the task box and
// start nothing) and a clickable recorded project; the Worlds preview opens the sample instead of explaining how.
import { act } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, click, q } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, settle } from "../../../test-support/park/shellHarness";
import { useApp } from "../app/context";
import { parkPath } from "../app/router";
import { HomePage } from "../pages/Home/HomePage";
import { WorldsPage } from "../pages/Worlds/WorldsPage";
import { FIRST_TASKS } from "./firstTask";
import { SAMPLE_WORLD_ID, isSampleHidden, wantsSample } from "./sampleChoice";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);
afterEach(cleanup);
beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* storage absent */
  }
});

function Both() {
  const app = useApp();
  return (
    <>
      <HomePage app={app} />
      <WorldsPage app={app} />
    </>
  );
}
async function setup() {
  const api = liveApi();
  api.getWorlds = vi.fn(async () => ({ data: [], source: "live" as const }));
  api.startWorld = vi.fn(async () => {
    throw new Error("a first task is never started by picking it");
  });
  const node = mountShell(<Both />, { api });
  await settle();
  return { api, node };
}

it("JUDGE_FIRST_RUN_F2_three_real_tasks_fill_the_task_box_and_start_nothing", async () => {
  const { api, node } = await setup();
  const card = q(node.m.container, ".park-first-task");
  expect(card.textContent).toContain("Start your first task");
  const picks = [...card.querySelectorAll<HTMLButtonElement>(".park-first-task__pick")];
  expect(picks.map((b) => b.textContent)).toEqual(FIRST_TASKS.map((t) => t.label));
  expect(FIRST_TASKS.map((t) => t.id)).toEqual(["trip", "suppliers", "url"]);
  const box = q(node.m.container, '[aria-label="Describe your task"]') as HTMLInputElement;
  for (const [i, pick] of picks.entries()) {
    click(pick);
    await settle();
    expect(box.value).toBe(FIRST_TASKS[i]?.prompt);
  }
  expect(api.startWorld).not.toHaveBeenCalled();
  expect(node.navigate).not.toHaveBeenCalled();
  // every task is plain work that touches no connected tool and sends nothing
  for (const t of FIRST_TASKS) expect(t.prompt).toMatch(/Do not (access|book|contact)/);
});

it("JUDGE_FIRST_RUN_F3_home_card_opens_the_recorded_sample_project_and_asks_for_it_in_the_list", async () => {
  const { node } = await setup();
  const watch = [
    ...node.m.container.querySelectorAll<HTMLButtonElement>(".park-first-task button"),
  ].find((b) => b.textContent === "Watch a recorded project");
  expect(watch).toBeTruthy();
  await act(async () => {
    click(watch as HTMLButtonElement);
  });
  expect(wantsSample()).toBe(true); // the list is read with ?include_sample=1, or the world page would not know the id
  expect(isSampleHidden()).toBe(false);
  expect(node.navigate).toHaveBeenCalledWith(parkPath("world", { id: SAMPLE_WORLD_ID }));
});

it("JUDGE_FIRST_RUN_F3_worlds_preview_opens_the_sample_in_plain_words", async () => {
  const { node } = await setup();
  const worlds = q(node.m.container, '[data-first-run-overview="worlds"]');
  expect(worlds.textContent).not.toContain("Use Show sample project");
  expect(worlds.textContent).toContain("A finished project you can replay. It is not your work.");
  const open = [...worlds.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === "Open the recorded sample project",
  );
  expect(open).toBeTruthy();
  await act(async () => {
    click(open as HTMLButtonElement);
  });
  expect(node.navigate).toHaveBeenCalledWith(parkPath("world", { id: SAMPLE_WORLD_ID }));
});
