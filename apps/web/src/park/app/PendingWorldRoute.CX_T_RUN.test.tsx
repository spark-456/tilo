// @vitest-environment happy-dom
// CX-T-RUN, revised by UX-SMOOTH (owner, 21 Oct): the World page opens the moment Start answers; a compact planning
// card on it (with the task's words) says the Director is planning until the plan, the first work or a stop is
// recorded. Nothing covers the page and nothing waits for the run.
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { PendingWorldRoute, markPendingWorld, pendingWorld } from "./PendingWorldRoute";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

type Feed = ((event: { type: string; ts?: string }) => void) | undefined;
function feed() {
  const box: { receive: Feed } = { receive: undefined };
  const client = {
    subscribeEvents: vi.fn(
      (_id: string, onEvent: (event: { type: string; ts?: string }) => void) => {
        box.receive = onEvent;
        return vi.fn();
      },
    ),
  };
  return { box, client };
}
const card = (root: HTMLElement) => root.querySelector("[data-testid='tt-plan-card']");

it("CX_T_RUN_the_world_page_opens_at_once_with_a_planning_card_until_the_plan_is_recorded", async () => {
  const { box, client } = feed();
  markPendingWorld("run-storyboard", "Prepare the team offsite");
  const rig = mount(
    <PendingWorldRoute worldId="run-storyboard" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent, "nothing waits for the run").toContain("World is visible");
  expect(card(rig.container)?.textContent).toContain("Director is planning");
  expect(card(rig.container)?.textContent).toContain("Waiting for world.planned");
  expect(rig.container.querySelector("[data-testid='run-blueprint']")?.textContent).toContain(
    "Prepare the team offsite",
  );
  await act(async () => box.receive?.({ type: "world.started" }));
  expect(card(rig.container)?.textContent).toContain("world.started");
  await act(async () => box.receive?.({ type: "world.planned" }));
  expect(rig.container.textContent).toContain("World is visible");
  expect(card(rig.container)).toBeNull();
  expect(rig.container.querySelector("[data-testid='run-blueprint']")).toBeNull();
  expect(pendingWorld("run-storyboard")).toBe(false);
});

it("CX_T_RUN_existing_world_skips_the_start_storyboard", () => {
  const client = { subscribeEvents: vi.fn() };
  const rig = mount(
    <PendingWorldRoute worldId="existing" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent).toContain("World is visible");
  expect(card(rig.container)).toBeNull();
  expect(client.subscribeEvents).not.toHaveBeenCalled();
});

it("CX_T_RUN_missing_event_feed_says_so_without_a_fake_loader", () => {
  markPendingWorld("no-feed");
  const rig = mount(
    <PendingWorldRoute worldId="no-feed" client={null}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  expect(rig.container.textContent).toContain("World updates are unavailable");
  expect(card(rig.container)).toBeNull();
  expect(rig.container.textContent).toContain("World is visible");
});

it("CX_T_RUN_failed_start_drops_the_card_and_releases_the_pending_route", async () => {
  const { box, client } = feed();
  markPendingWorld("failed-start");
  const rig = mount(
    <PendingWorldRoute worldId="failed-start" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  await act(async () => box.receive?.({ type: "world.failed" }));
  expect(card(rig.container)).toBeNull();
  expect(rig.container.textContent, "the World page names the stop").toContain("World is visible");
  expect(pendingWorld("failed-start")).toBe(false);
});

it("CX_T_RUN_planning_card_never_covers_a_live_world_and_goes_with_the_first_recorded_work", async () => {
  const { box, client } = feed();
  markPendingWorld("pool-handoff", "Plan a team day");
  const rig = mount(
    <PendingWorldRoute worldId="pool-handoff" client={client}>
      <p>World is visible</p>
    </PendingWorldRoute>,
  );
  const host = rig.container.querySelector("[data-testid='tt-pool-host']");
  expect(host?.querySelector("[data-testid='tt-plan-card']")).not.toBeNull();
  expect(host?.querySelector(".tt-pool-overlay, .tt-pool-scrim")).toBeNull();
  expect(host?.textContent).toContain("World is visible");
  await act(async () => box.receive?.({ type: "agent.spawned" }));
  expect(card(rig.container)).toBeNull();
  expect(rig.container.querySelector("[data-testid='tt-pool-host']")).toBe(host);
  expect(pendingWorld("pool-handoff")).toBe(false);
});
