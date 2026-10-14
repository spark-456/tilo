// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, q } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { worlds } from "../api/fixtures/worlds";
import type { World } from "../api/types";
import { useApp } from "../app/context";
import { AgendaPage } from "../pages/Agenda/AgendaPage";
import { LedgerPage } from "../pages/Ledger/LedgerPage";
import { SkillsPage } from "../pages/Skills/SkillsPage";
import { TeamPage } from "../pages/Team/TeamPage";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);
afterEach(cleanup);
const real = { ...worlds({}, [])[0], id: "w_real", sample: false } as World;
const pages = [AgendaPage, SkillsPage, LedgerPage, TeamPage];
function AllPages() {
  const app = useApp();
  return (
    <>
      {pages.map((Page) => (
        <Page key={Page.name} app={app} />
      ))}
    </>
  );
}
async function setup(list: World[] = []) {
  const api = liveApi();
  api.getWorlds = vi.fn(async () => ({ data: list, source: "live" as const }));
  api.startWorld = vi.fn(async () => ({
    data: { ok: true as const, world: real },
    source: "live" as const,
  }));
  for (const name of ["startWorld", "decide", "undo", "setPref", "saveSkill"] as const)
    vi.spyOn(api, name);
  const node = mountShell(<AllPages />, { api });
  await settle();
  return { api, node };
}
it("FIRST_RUN_HR_1_four_live_pages_show_labelled_fixture_panels_and_clicks_never_write", async () => {
  const { api, node } = await setup();
  expect(node.m.container.querySelectorAll("[data-first-run-panels]")).toHaveLength(4);
  for (const panel of node.m.container.querySelectorAll(".park-first-run-card"))
    expect(panel.textContent).toContain("Sample");
  expect(node.m.container.textContent).toContain("Fictional");
  // JUDGE-FIRST-RUN F1/F4: Agenda, Skills and Team keep their real page and add the labelled examples below it.
  for (const page of ["agenda", "skills", "team"])
    expect(
      node.m.container.querySelector(`[data-first-run-panels="${page}"] h2`)?.textContent,
    ).toBe("Recorded examples");
  expect(node.m.container.querySelector('[data-first-run-panels="ledger"] h1')?.textContent).toBe(
    "Ledger",
  );
  click(q(node.m.container, "[data-first-run-panels] button"));
  expect(seen.store.getState().toast?.message).toContain("sample data");
  for (const name of ["startWorld", "decide", "undo", "setPref", "saveSkill"] as const)
    expect(api[name]).not.toHaveBeenCalled();
});
it("FIRST_RUN_HR_1_a_real_start_hides_every_preview_and_an_existing_world_never_shows_one", async () => {
  const { node } = await setup();
  expect(node.m.container.querySelectorAll("[data-first-run-panels]")).toHaveLength(4);
  await act(async () => {
    expect(await seen.store.startWorld("quick", "a real task")).toBe(true);
  });
  expect(node.m.container.querySelector("[data-first-run-panels]")).toBeNull();
  node.m.unmount();
  const own = await setup([real]);
  expect(own.node.m.container.querySelector("[data-first-run-panels]")).toBeNull();
});
