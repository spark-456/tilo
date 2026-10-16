// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { PendingWorldRoute, markPendingWorld, pendingWorld } from "./PendingWorldRoute";

afterEach(() => cleanup());

it("test_FR_INT_01_run_opens_world_only_after_a_recorded_plan_or_start", async () => {
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
  expect(rig.container.textContent).toContain("Tilo is planning your world");
  expect(rig.container.textContent).not.toContain("World loaded");
  expect(client.subscribeEvents).toHaveBeenCalledWith(
    "new-world",
    expect.any(Function),
    expect.any(Function),
  );
  await act(async () => receive?.({ type: "world.requested" }));
  expect(rig.container.textContent).toContain("Tilo is planning your world");
  await act(async () => receive?.({ type: "world.planned" }));
  expect(rig.container.textContent).toContain("World loaded");
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

it("test_FR_INT_01_run_shows_recorded_start_then_opens_world_on_recorded_plan", async () => {
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
  expect(rig.container.textContent).toContain("world.started");
  expect(rig.container.textContent).not.toContain("World loaded");
  await act(async () => receive?.({ type: "world.planned" }));
  expect(rig.container.textContent).toContain("World loaded");
});
