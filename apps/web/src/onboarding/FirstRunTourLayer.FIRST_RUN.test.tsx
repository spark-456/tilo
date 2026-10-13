// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../test-support/park/appHarness";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { worlds } from "../park/api/fixtures/worlds";
import { ParkProvider, useParkStore } from "../park/app/context";
import type { ParkStore } from "../park/app/store";
import FirstRunTourLayer from "./FirstRunTourLayer";

beforeEach(() => window.history.replaceState(null, "", "/?onboarding=1"));
afterEach(() => {
  window.history.replaceState(null, "", "/");
  cleanup();
  window.localStorage.clear();
});
let store: ParkStore;
function Layer() {
  store = useParkStore();
  return (
    <div data-park>
      <FirstRunTourLayer />
    </div>
  );
}
const example = worlds({}, [])[0];
if (!example) throw new Error("Missing world fixture");
const real = { ...example, id: "w_real", sample: false };

it("FIRST_RUN_FR_UX_13_actual_hook_closes_invitation_after_first_real_start", async () => {
  const api = fakeApi();
  api.getWorlds = vi.fn(async () => ({ data: [], source: "live" as const }));
  api.startWorld.mockResolvedValue({ data: { world: real }, source: "live" });
  mount(
    <ParkProvider api={api} schedule={fakeScheduler().schedule}>
      <Layer />
    </ParkProvider>,
  );
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  await act(async () => undefined);
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain("Take a tour of Home?");
  await act(async () => {
    await store.startWorld("quick", "a task");
  });
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});

it.each(["real", "failed"])(
  "FIRST_RUN_FR_UX_13_actual_hook_suppresses_%s_account_invitation",
  async (state) => {
    const api = fakeApi();
    api.getWorlds = vi.fn(async () => {
      if (state === "failed") throw new Error("unavailable");
      return { data: [real], source: "live" as const };
    });
    mount(
      <ParkProvider api={api}>
        <Layer />
      </ParkProvider>,
    );
    await act(async () => undefined);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    for (const write of [api.startWorld, api.decide, api.undo, api.setPref])
      expect(write).not.toHaveBeenCalled();
  },
);
