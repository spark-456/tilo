// @vitest-environment happy-dom
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { setReplayPoint } from "../world/replay";
import { S_10 } from "./S_10";
import { ANNOUNCE_DEBOUNCE_MS } from "./storyAnnounce";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ALL: readonly Event[] = [...EVENTS_VILLAGE_BASIC].sort((a, b) => a.seq - b.seq);
// A run that has not ended: the recorded fixture minus its last events.
const LIVE = ALL.slice(0, 40);

/** A client that is not the fixture client (so Story treats it as a real one) whose events the test
 * delivers by hand, as a server would. */
function liveClient() {
  const base = new FixtureClient();
  let emit: (e: Event) => void = () => undefined;
  const client = new Proxy(base, {
    get(target, key) {
      if (key === "subscribeEvents") {
        return (_world: string, on: (e: Event) => void) => {
          emit = on;
          return () => undefined;
        };
      }
      const value = Reflect.get(target, key, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
    getPrototypeOf: () => Object.prototype, // `instanceof FixtureClient` is false
  });
  const send = (events: readonly Event[]) => {
    for (const e of events) emit(e);
  };
  return { client, send };
}

describe("FR-WLD-11 Story announces only what arrives live", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    setReplayPoint(FIXTURE_WORLD_ID, null);
    vi.useRealTimers();
  });

  async function open() {
    // The fixture client imports its layout on first use; with it already loaded the call settles
    // inside act(), which fake timers cannot wait on for a real module load.
    await Promise.all([import("../api/fixtures/layout"), import("../api/fixtures/events")]);
    const { client, send } = liveClient();
    const container = document.createElement("div");
    document.body.append(container);
    await act(async () => {
      createRoot(container).render(
        <ClientProvider client={client as unknown as FixtureClient}>
          <S_10 params={[FIXTURE_WORLD_ID]} />
        </ClientProvider>,
      );
    });
    const wait = (ms: number) =>
      act(async () => {
        vi.advanceTimersByTime(ms);
      });
    const said = () => container.querySelector("output.sr-only")?.textContent ?? "";
    const rows = () => container.querySelectorAll(".story-list li").length;
    return { send: (e: readonly Event[]) => act(async () => send(e)), wait, said, rows };
  }

  it("announces rows that arrive live after the first load, once", async () => {
    const { send, wait, said } = await open();
    await send(LIVE.slice(0, 10));
    await wait(ANNOUNCE_DEBOUNCE_MS * 2);
    expect(said()).toBe("");
    await send(LIVE.slice(10, 30));
    await wait(ANNOUNCE_DEBOUNCE_MS + 50);
    expect(said()).toMatch(/^20 new events\. Latest: /);
  });

  it("says nothing on a forward scrub with a real client (10 rows to 40)", async () => {
    const { send, wait, said, rows } = await open();
    await send(LIVE);
    setReplayPoint(FIXTURE_WORLD_ID, (LIVE[9] as Event).seq);
    await wait(ANNOUNCE_DEBOUNCE_MS * 2);
    expect(rows()).toBe(10);
    setReplayPoint(FIXTURE_WORLD_ID, (LIVE[39] as Event).seq);
    await act(async () => void 0);
    expect(rows()).toBe(40);
    await wait(ANNOUNCE_DEBOUNCE_MS * 2);
    expect(said()).toBe("");
  });

  it("says nothing once the run has ended", async () => {
    const { send, wait, said } = await open();
    await send(ALL.slice(0, 10));
    await send(ALL);
    await wait(ANNOUNCE_DEBOUNCE_MS * 2);
    expect(said()).toBe("");
  });
});
