import { describe, expect, it } from "vitest";
import type { TiloClient } from "../api/client";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { findItem } from "./findItem";
import { reduce } from "./reducer";
import { creditsUsed, elapsed, waitingForYou, watchRun } from "./runLog";

const events = EVENTS_VILLAGE_BASIC;

describe("PRD-18.3 AGW-08 run log: HUD figures derive only from recorded events", () => {
  it("sums the credits the events record, ending on the run's 13 (world.completed)", () => {
    expect(creditsUsed([])).toBe(0);
    expect(creditsUsed(events)).toBe(13);
  });

  it("counts an approval as waiting from its request until it is resolved", () => {
    const requested = events.findIndex((e) => e.type === "approval.requested");
    const resolved = events.findIndex((e) => e.type === "approval.resolved");
    expect(waitingForYou(events.slice(0, requested))).toBe(0);
    expect(waitingForYou(events.slice(0, requested + 1))).toBe(1);
    expect(waitingForYou(events.slice(0, resolved + 1))).toBe(0);
  });

  it("shows time as m:ss since the first recorded event", () => {
    expect(elapsed(events, events[0] as (typeof events)[number])).toBe("0:00");
    expect(elapsed(events, events[2] as (typeof events)[number])).toBe("0:22");
  });
});

describe("FR-WLD-04 run log: the stage watches the run the lenses read", () => {
  /** A client whose events arrive when the test says so. */
  function manual() {
    let push: (e: (typeof events)[number]) => void = () => undefined;
    let subscribed = 0;
    const client = {
      subscribeEvents: (_id: string, onEvent: typeof push) => {
        subscribed++;
        push = onEvent;
        return () => undefined;
      },
    } as unknown as TiloClient;
    return { client, push: (e: (typeof events)[number]) => push(e), count: () => subscribed };
  }

  it("hands over what the run already holds, then each new event once, in seq order", () => {
    const m = manual();
    const first = watchRun(m.client, "w_watch_a", () => undefined); // starts the run's one subscription
    for (const e of events.slice(0, 3)) m.push(e);
    const seen: number[] = [];
    const stop = watchRun(m.client, "w_watch_a", (e) => seen.push(e.seq));
    expect(seen).toEqual([1, 2, 3]); // a late watcher is caught up at once
    m.push(events[3] as (typeof events)[number]);
    m.push(events[3] as (typeof events)[number]); // a repeat is ignored (FR-WLD-04)
    m.push(events[2] as (typeof events)[number]); // so is one out of order
    expect(seen).toEqual([1, 2, 3, 4]);
    stop();
    m.push(events[4] as (typeof events)[number]);
    expect(seen).toEqual([1, 2, 3, 4]);
    expect(m.count()).toBe(1); // one subscription per client and world, however many watchers
    first();
  });
});

describe("PRD-18.3 S-05 inspect: finds any item of the layout and its state from the events", () => {
  const layout = LAYOUT_VILLAGE_BASIC;
  const final = reduce(layout, events);

  it("finds a building, a district, a level and an agent, and nothing for an unknown id", () => {
    expect(findItem(layout, "B1")?.name).toBe("Mail Room");
    expect(findItem(layout, "D1")?.kind).toBe("District");
    expect(findItem(layout, "L1")?.kind).toBe("Level");
    expect(findItem(layout, "A_s1")?.kind).toBe("Agent");
    expect(findItem(layout, "B99")).toBeNull();
  });

  it("reports hidden before any event and finished after the run", () => {
    expect(findItem(layout, "B1")?.state(reduce(layout, []))).toBe("Not planned yet");
    expect(findItem(layout, "B1")?.state(final)).toBe("Finished");
    expect(findItem(layout, "L1")?.state(final)).toBe("Finished");
  });
});
