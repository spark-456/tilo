// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { PendingWorldRoute, markPendingWorld, pendingWorld } from "./PendingWorldRoute";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

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
  const rig = mount(
    <PendingWorldRoute worldId="existing" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent).toContain("World is visible");
  expect(client.subscribeEvents).not.toHaveBeenCalled();
});

it("CX_T_RUN_missing_event_feed_shows_an_error_without_a_fake_loader", () => {
  markPendingWorld("no-feed");
  const rig = mount(
    <PendingWorldRoute worldId="no-feed" client={null}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent).toContain("World updates are unavailable");
  expect(rig.container.querySelector("[data-testid='tt-loading']")).toBeNull();
  expect(rig.container.textContent).not.toContain("World is visible");
});

it("CX_T_RUN_failed_start_stops_the_loader_and_releases_the_pending_route", async () => {
  let receive: ((event: { type: string }) => void) | undefined;
  const client = {
    subscribeEvents: vi.fn((_id: string, onEvent: (event: { type: string }) => void) => {
      receive = onEvent;
      return vi.fn();
    }),
  };
  markPendingWorld("failed-start");
  const rig = mount(
    <PendingWorldRoute worldId="failed-start" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  await act(async () => receive?.({ type: "world.failed" }));
  expect(rig.container.textContent).toContain("This world stopped");
  expect(rig.container.querySelector("[data-testid='tt-loading']")).toBeNull();
  expect(pendingWorld("failed-start")).toBe(false);
});

it("CX_T_RUN_pending_blueprint_stays_until_the_recorded_world_started_event", async () => {
  let receive: ((event: { type: string }) => void) | undefined;
  const client = {
    subscribeEvents: vi.fn((_id: string, onEvent: (event: { type: string }) => void) => {
      receive = onEvent;
      return vi.fn();
    }),
  };
  markPendingWorld("pending-blueprint", "Prepare the team offsite");
  const rig = mount(
    <PendingWorldRoute worldId="pending-blueprint" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.querySelector("[data-testid='run-blueprint']")?.textContent).toContain(
    "Prepare the team offsite",
  );
  expect(rig.container.textContent).toContain("Waiting for world.started");
  await act(async () => receive?.({ type: "agent.spawned" }));
  expect(rig.container.querySelector("[data-testid='run-blueprint']")).not.toBeNull();
  await act(async () => receive?.({ type: "world.started" }));
  expect(rig.container.querySelector("[data-testid='run-blueprint']")).toBeNull();
});

it("CX_T_RUN_pool_stays_mounted_while_the_recorded_plan_reveals_the_world", async () => {
  vi.useFakeTimers();
  let receive: ((event: { type: string; ts?: string }) => void) | undefined;
  const client = {
    subscribeEvents: vi.fn(
      (_id: string, onEvent: (event: { type: string; ts?: string }) => void) => {
        receive = onEvent;
        return vi.fn();
      },
    ),
  };
  markPendingWorld("pool-handoff", "Plan a team day");
  const rig = mount(
    <PendingWorldRoute worldId="pool-handoff" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  await act(async () => receive?.({ type: "world.started", ts: "2026-10-16T10:00:00.000Z" }));
  const host = rig.container.querySelector("[data-testid='tt-pool-host']");
  expect(host).not.toBeNull();
  expect(host?.querySelector("[data-phase]")).toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(300));
  expect(host?.querySelector("[data-phase='leap']")).not.toBeNull();
  await act(async () => receive?.({ type: "world.planned", ts: "2026-10-16T10:00:00.400Z" }));
  expect(rig.container.querySelector("[data-testid='tt-pool-host']")).toBe(host);
  expect(host?.textContent).toContain("World is visible");
});
