// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { PendingWorldRoute, markPendingWorld } from "./PendingWorldRoute";

afterEach(cleanup);

it("CX_T_RUN_starts_the_storyboard_only_from_recorded_world_events", async () => {
  let receive: ((event: { type: string }) => void) | undefined;
  const client = {
    subscribeEvents: vi.fn((_id: string, onEvent: (event: { type: string }) => void) => {
      receive = onEvent;
      return vi.fn();
    }),
  };
  markPendingWorld("run-storyboard");
  const rig = mount(
    <PendingWorldRoute worldId="run-storyboard" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent).toContain("Waiting for world.started");
  expect(rig.container.textContent).not.toContain("World is visible");
  await act(async () => receive?.({ type: "agent.spawned" }));
  expect(rig.container.textContent).toContain("Waiting for world.started");
  await act(async () => receive?.({ type: "world.started" }));
  expect(rig.container.textContent).toContain("world.started");
  expect(rig.container.textContent).not.toContain("World is visible");
  await act(async () => receive?.({ type: "world.planned" }));
  expect(rig.container.textContent).toContain("World is visible");
  expect(rig.container.textContent).not.toContain("Waiting for world.started");
});

it("CX_T_RUN_existing_world_skips_the_start_storyboard", () => {
  const client = { subscribeEvents: vi.fn() };
  const rig = mount(<PendingWorldRoute worldId="existing" client={client}><p>World is visible</p></PendingWorldRoute>);
  expect(rig.container.textContent).toContain("World is visible");
  expect(client.subscribeEvents).not.toHaveBeenCalled();
});

it("CX_T_RUN_missing_event_feed_shows_an_error_without_a_fake_loader", () => {
  markPendingWorld("no-feed");
  const rig = mount(<PendingWorldRoute worldId="no-feed" client={null}><p>World is visible</p></PendingWorldRoute>);
  expect(rig.container.textContent).toContain("World updates are unavailable");
  expect(rig.container.querySelector("[data-testid='tt-loading']")).toBeNull();
  expect(rig.container.textContent).not.toContain("World is visible");
});
