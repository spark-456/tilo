// @vitest-environment happy-dom
// FR-WLD-05 / CP2 (issue #248): the screens follow the live run's own world and events. Nothing is
// requested before the run's events say it can be (delivery after world.completed, layout after
// world.started), and the Needs-you screens read the world their address names, not the fixture's.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { S_06 } from "../screens/S_06";
import { S_07 } from "../screens/S_07";
import { S_12 } from "../screens/S_12";
import { WorldPanels } from "../screens/WorldPanels";
import { followRun } from "./runLog";
import { alsoWorld, withWorld, worldOf } from "./worldContext";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A client whose run has recorded the events up to `seq`, which counts every call it gets. */
function spied(seq: number) {
  const client = new FixtureClient();
  const asked: string[] = [];
  const getDelivery = vi.spyOn(client, "getDelivery");
  const getLayout = vi.spyOn(client, "getLayout");
  const listCards = vi.spyOn(client, "listCards");
  client.subscribeEvents = (world, onEvent) => {
    asked.push(world);
    for (const e of EVENTS_VILLAGE_BASIC) if (e.seq <= seq) onEvent({ ...e, world_id: world });
    return () => undefined;
  };
  return { client, asked, getDelivery, getLayout, listCards };
}

async function render(client: TiloClient, ui: React.ReactNode) {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(<ClientProvider client={client}>{ui}</ClientProvider>);
  });
  return container;
}

const COMPLETED = EVENTS_VILLAGE_BASIC.find((e) => e.type === "world.completed")?.seq ?? 0;

describe("FR-WLD-05 CP2: the delivery is asked for only once world.completed is recorded", () => {
  it("S-04 HUD does not call getDelivery while the run is going, and calls it once after", async () => {
    const going = spied(COMPLETED - 1);
    await render(going.client, <WorldPanels worldId="w_going" />);
    expect(going.getDelivery).not.toHaveBeenCalled();
    const done = spied(COMPLETED);
    await render(done.client, <WorldPanels worldId="w_done" />);
    expect(done.getDelivery).toHaveBeenCalledTimes(1);
    expect(done.getDelivery).toHaveBeenCalledWith("w_done");
  });

  it("S-12 says the run is not finished without asking the server, then shows the delivery", async () => {
    const going = spied(COMPLETED - 1);
    const page = await render(going.client, <S_12 params={["w_going2"]} />);
    expect(going.getDelivery).not.toHaveBeenCalled();
    expect(page.textContent).toContain("This run has not finished yet.");
    const done = spied(COMPLETED);
    const finished = await render(done.client, <S_12 params={["w_done2"]} />);
    expect(done.getDelivery).toHaveBeenCalledTimes(1);
    expect(finished.textContent).toContain("Finished:");
  });
});

describe("FR-WLD-05 CP2: Needs you follows the world its address names", () => {
  it("S-06 and S-07 read ?world=<id>: its events and its cards, not the fixture world's", async () => {
    window.history.pushState({}, "", "/needs-you?world=w_live_1");
    const queue = spied(40);
    await render(queue.client, <S_06 />);
    expect(queue.asked).toEqual(["w_live_1"]);
    expect(queue.listCards).toHaveBeenCalledWith("w_live_1");
    expect(queue.getLayout).toHaveBeenCalledWith("w_live_1");

    window.history.pushState({}, "", "/needs-you/gate?world=w_live_2");
    const gate = spied(40);
    await render(gate.client, <S_07 />);
    expect(gate.asked).toEqual(["w_live_2"]);
    expect(gate.listCards).toHaveBeenCalledWith("w_live_2");
  });

  it("without ?world= the screens keep the fixture world, as before", async () => {
    window.history.pushState({}, "", "/needs-you");
    const queue = spied(40);
    await render(queue.client, <S_06 />);
    expect(queue.asked).toEqual(["w_village_basic"]);
  });

  it("a world's links carry its id, and the fixture world's addresses stay plain", () => {
    expect(withWorld("/needs-you", "w_village_basic")).toBe("/needs-you");
    expect(withWorld("/needs-you", "w 1")).toBe("/needs-you?world=w%201");
    expect(alsoWorld("/needs-you/gate?run=r&gate=G1", "w1")).toBe(
      "/needs-you/gate?run=r&gate=G1&world=w1",
    );
    expect(worldOf("/world/w1/story", "")).toBe("w1");
    expect(worldOf("/needs-you", "?world=w2")).toBe("w2");
    expect(worldOf("/world/w3", "?world=w2")).toBe("w3");
    expect(worldOf("/needs-you", "")).toBeNull();
    expect(worldOf("/world/%E0", "")).toBeNull();
  });
});

describe("FR-WLD-05 CP2: the stage's live feed shares the page's one subscription", () => {
  it("hands over events already received, then each new one, once, in seq order", () => {
    const client = new FixtureClient();
    let push: ((e: (typeof EVENTS_VILLAGE_BASIC)[number]) => void) | undefined;
    const subscribe = vi.fn(
      (_: string, onEvent: (e: (typeof EVENTS_VILLAGE_BASIC)[number]) => void) => {
        push = onEvent;
        onEvent(EVENTS_VILLAGE_BASIC[0] as (typeof EVENTS_VILLAGE_BASIC)[number]);
        return () => undefined;
      },
    );
    client.subscribeEvents = subscribe;
    const seen: number[] = [];
    const stop = followRun(client, "w_feed", (e) => seen.push(e.seq));
    push?.(EVENTS_VILLAGE_BASIC[1] as (typeof EVENTS_VILLAGE_BASIC)[number]);
    push?.(EVENTS_VILLAGE_BASIC[1] as (typeof EVENTS_VILLAGE_BASIC)[number]); // a repeat
    const late: number[] = [];
    followRun(client, "w_feed", (e) => late.push(e.seq)); // joins mid-run: replays what is known
    stop();
    push?.(EVENTS_VILLAGE_BASIC[2] as (typeof EVENTS_VILLAGE_BASIC)[number]);
    expect(subscribe).toHaveBeenCalledTimes(1);
    expect(seen).toEqual([EVENTS_VILLAGE_BASIC[0]?.seq, EVENTS_VILLAGE_BASIC[1]?.seq]);
    expect(late).toEqual([
      EVENTS_VILLAGE_BASIC[0]?.seq,
      EVENTS_VILLAGE_BASIC[1]?.seq,
      EVENTS_VILLAGE_BASIC[2]?.seq,
    ]);
  });
});
