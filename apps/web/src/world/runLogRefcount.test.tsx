// @vitest-environment happy-dom
// #294: a world's events subscription (the run log) lives while something reads the world and closes
// shortly after the last reader leaves, so leaving /world/:id stops its polling. A lens switch,
// which unmounts one reader and mounts the next, never closes it.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TiloClient } from "../api/client";
import { HttpClient } from "../api/http";
import { CLOSE_AFTER_MS, useRunLog, useRunStatus, watchRun } from "./runLog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A client that only counts how many subscriptions are open per world. */
function counting() {
  const open = new Map<string, number>();
  let started = 0;
  const client = {
    subscribeEvents: (id: string) => {
      started += 1;
      open.set(id, (open.get(id) ?? 0) + 1);
      return () => open.set(id, (open.get(id) ?? 1) - 1);
    },
  } as unknown as TiloClient;
  const openNow = () => [...open.values()].reduce((a, b) => a + b, 0);
  return { client, started: () => started, openNow };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  document.body.replaceChildren();
});

describe("#294 the run log closes a world's subscription after its last reader leaves", () => {
  it("stays open while a reader holds it and closes CLOSE_AFTER_MS after the last one lets go", () => {
    const c = counting();
    const a = watchRun(c.client, "w_ref_a", () => undefined);
    const b = watchRun(c.client, "w_ref_a", () => undefined);
    expect(c.started()).toBe(1); // one subscription, shared
    a();
    vi.advanceTimersByTime(CLOSE_AFTER_MS * 2);
    expect(c.openNow()).toBe(1); // b still reads it
    b();
    vi.advanceTimersByTime(CLOSE_AFTER_MS - 1);
    expect(c.openNow()).toBe(1);
    vi.advanceTimersByTime(1);
    expect(c.openNow()).toBe(0);
  });

  it("a lens switch (the next reader arrives within the grace) never restarts the subscription", () => {
    const c = counting();
    const leave = watchRun(c.client, "w_ref_b", () => undefined);
    leave();
    vi.advanceTimersByTime(50); // the next lens mounts a frame or two later
    const next = watchRun(c.client, "w_ref_b", () => undefined);
    vi.advanceTimersByTime(CLOSE_AFTER_MS * 3);
    expect(c.started()).toBe(1);
    expect(c.openNow()).toBe(1);
    next();
    vi.advanceTimersByTime(CLOSE_AFTER_MS);
    expect(c.openNow()).toBe(0);
  });

  it("30 rapid world switches leave nothing open once the last is gone", () => {
    const c = counting();
    for (let i = 0; i < 30; i++) watchRun(c.client, `w_ref_sw_${i}`, () => undefined)();
    vi.advanceTimersByTime(CLOSE_AFTER_MS);
    expect(c.started()).toBe(30);
    expect(c.openNow()).toBe(0);
  });

  it("coming back after the close reads the world afresh: the old events are gone and a new subscription starts", () => {
    const c = counting();
    watchRun(c.client, "w_ref_c", () => undefined)();
    vi.advanceTimersByTime(CLOSE_AFTER_MS);
    const again = watchRun(c.client, "w_ref_c", () => undefined);
    expect(c.started()).toBe(2);
    expect(c.openNow()).toBe(1);
    again();
  });
});

describe("#294 requests stop after leaving a world (HTTP client, a run that never starts)", () => {
  const stuckApi = () => {
    const urls: string[] = [];
    const fetch = vi.fn(async (url: string | URL | Request) => {
      urls.push(new URL(String(url)).pathname);
      return new Response(JSON.stringify({ events: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }) as unknown as typeof globalThis.fetch;
    return { urls, client: new HttpClient({ baseUrl: "https://api.test", fetch, pollMs: 1000 }) };
  };

  function Reader({ client, world }: { client: TiloClient; world: string }) {
    useRunLog(client, world);
    useRunStatus(client, world);
    return null;
  }

  it("leaving /world/:id stops its events polling within the grace and one poll", async () => {
    const { urls, client } = stuckApi();
    const root = createRoot(document.createElement("div"));
    await act(async () => root.render(<Reader client={client} world="w_stuck" />));
    await act(async () => void (await vi.advanceTimersByTimeAsync(4000)));
    expect(urls.length).toBeGreaterThanOrEqual(4); // polling while it is shown
    await act(async () => root.unmount());
    await act(async () => void (await vi.advanceTimersByTimeAsync(CLOSE_AFTER_MS + 1000)));
    const after = urls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(20_000)));
    expect(urls).toHaveLength(after);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rapid switches between worlds poll only the world on show", async () => {
    const { urls, client } = stuckApi();
    const root = createRoot(document.createElement("div"));
    for (let i = 0; i < 30; i++) {
      await act(async () => root.render(<Reader client={client} world={`w_switch_${i}`} />));
      await act(async () => void (await vi.advanceTimersByTimeAsync(100)));
    }
    await act(async () => void (await vi.advanceTimersByTimeAsync(CLOSE_AFTER_MS + 1000)));
    const settled = urls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(10_000)));
    const polled = new Set(urls.slice(settled).map((u) => u.split("/")[2]));
    expect(polled).toEqual(new Set(["w_switch_29"])); // only the last one still polls
    await act(async () => root.unmount());
    await act(async () => void (await vi.advanceTimersByTimeAsync(CLOSE_AFTER_MS + 1000)));
    const end = urls.length;
    await act(async () => void (await vi.advanceTimersByTimeAsync(10_000)));
    expect(urls).toHaveLength(end);
  });
});
