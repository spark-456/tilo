// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { PendingWorldRoute, markPendingWorld, pendingWorld } from "./PendingWorldRoute";

afterEach(() => cleanup());

// UX-SMOOTH (owner, 21 Oct): the run opens its world at once; only the planning card waits for the recorded plan.
it("test_FR_INT_01_run_opens_world_at_once_and_the_card_waits_for_a_recorded_plan", async () => {
  let receive: ((event: { type: string }) => void) | undefined;
  const stop = vi.fn();
  const client = {
    subscribeEvents: vi.fn((_id: string, onEvent: (event: { type: string }) => void) => {
      receive = onEvent;
      return stop;
    }),
  };
  markPendingWorld("new-world");
  expect(pendingWorld("new-world")).toBe(true);
  const rig = mount(
    <PendingWorldRoute worldId="new-world" client={client}>
      <p>World loaded</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent).toContain("Director is planning");
  expect(rig.container.textContent).toContain("World loaded");
  expect(client.subscribeEvents).toHaveBeenCalledWith(
    "new-world",
    expect.any(Function),
    expect.any(Function),
  );
  await act(async () => receive?.({ type: "world.requested" }));
  expect(rig.container.textContent).toContain("Director is planning");
  await act(async () => receive?.({ type: "world.planned" }));
  expect(rig.container.textContent).toContain("World loaded");
  expect(rig.container.textContent).not.toContain("Director is planning");
  expect(pendingWorld("new-world")).toBe(false);
  expect(stop).toHaveBeenCalledOnce();
});

it("test_FR_INT_01_run_opens_world_existing_bookmarks_without_a_pending_state", () => {
  const client = { subscribeEvents: vi.fn() };
  const rig = mount(
    <PendingWorldRoute worldId="existing-world" client={client}>
      <p>World loaded</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent).toContain("World loaded");
  expect(client.subscribeEvents).not.toHaveBeenCalled();
});

it("test_FR_INT_01_run_opens_world_on_recorded_start_and_drops_the_card_on_recorded_plan", async () => {
  let receive: ((event: { type: string }) => void) | undefined;
  const client = {
    subscribeEvents: vi.fn((_id: string, onEvent: (event: { type: string }) => void) => {
      receive = onEvent;
      return vi.fn();
    }),
  };
  markPendingWorld("started-world");
  const rig = mount(
    <PendingWorldRoute worldId="started-world" client={client}>
      <p>World loaded</p>
    </PendingWorldRoute>,
  );
  await act(async () => receive?.({ type: "world.started" }));
  // from the recorded start the World page is open, with a planning card until the recorded plan
  expect(rig.container.textContent).toContain("world.started");
  expect(rig.container.textContent).toContain("World loaded");
  await act(async () => receive?.({ type: "world.planned" }));
  expect(rig.container.textContent).toContain("World loaded");
  expect(rig.container.textContent).not.toContain("world.started");
});
