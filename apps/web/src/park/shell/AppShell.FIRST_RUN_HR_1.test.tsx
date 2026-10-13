// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, q } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { worlds } from "../api/fixtures/worlds";
import type { World } from "../api/types";
import { AppShell } from "./AppShell";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);
afterEach(() => {
  cleanup();
  localStorage.clear();
});
const real = { ...worlds({}, [])[0], id: "w_real", sample: false } as World;
async function setup(list: World[] = []) {
  const api = liveApi();
  api.getWorlds = vi.fn(async () => ({ data: list, source: "live" as const }));
  api.getNotifications = vi.fn(async () => ({ data: [], source: "live" as const }));
  api.startWorld = vi.fn(async () => ({
    data: { world: real, ok: true as const },
    source: "live" as const,
  }));
  for (const name of ["decide", "undo", "setPref"] as const) vi.spyOn(api, name);
  const node = mountShell(
    <AppShell>
      <div>Page</div>
    </AppShell>,
    { api },
  );
  await settle();
  act(() => seen.store.toggleMenu("notif"));
  return { api, node };
}
it("FIRST_RUN_HR_1_empty_live_account_gets_labelled_read_only_notifications", async () => {
  const { api, node } = await setup();
  const rows = [...document.querySelectorAll<HTMLButtonElement>(".park-shell__nrow")];
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) expect(row.textContent).toContain("Sample");
  click(q(document.body, ".park-shell__nrow"));
  expect(seen.store.getState().toast?.message).toContain("sample data");
  expect(seen.store.getState().wl).toBeNull();
  expect(node.navigate).not.toHaveBeenCalled();
  for (const name of ["startWorld", "decide", "undo", "setPref"] as const)
    expect(api[name]).not.toHaveBeenCalled();
});
it("FIRST_RUN_HR_1_existing_real_world_and_new_real_start_remove_all_shell_samples", async () => {
  const { node } = await setup();
  expect(document.querySelector(".park-first-run-banner")).not.toBeNull();
  await act(async () => {
    await seen.store.startWorld("quick", "a real task");
  });
  expect(document.querySelector(".park-first-run-banner")).toBeNull();
  expect(document.querySelector(".park-shell__nrow")).toBeNull();
  node.m.unmount();
  await setup([real]);
  expect(document.querySelector(".park-first-run-banner")).toBeNull();
  expect(document.querySelector(".park-shell__nrow")).toBeNull();
});
