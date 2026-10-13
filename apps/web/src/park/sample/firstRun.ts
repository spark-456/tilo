import type { Api } from "../api/index";
import type { ApiResult, World } from "../api/types";
import type { ParkStore } from "../app/store";

/** FIRST-RUN / HR-1: provider-local, fail-closed sample eligibility. No persistence or writes. */
export function createFirstRun(api: Api, store: ParkStore, demo: boolean) {
  let first = demo;
  let realSeen = false;
  let fixtureSession = demo;
  let loaded = demo;
  let pending = false;
  let generation = 0;
  let stop: (() => void) | undefined;
  const listeners = new Set<() => void>();
  const hasAdded = () => store.getState().added.some((world) => world.sample !== true);
  const publish = (value: boolean) => {
    const next = demo || (!realSeen && value);
    if (first === next) return;
    first = next;
    for (const listener of listeners) listener();
  };
  const noteAdded = () => {
    if (!fixtureSession && hasAdded()) {
      realSeen = true;
      publish(false);
    }
  };
  return {
    getState: () => demo || (!realSeen && first && (fixtureSession || !hasAdded())),
    ticket: () => generation,
    note(result: ApiResult<World[]>, ticket: number) {
      if (ticket !== generation) return;
      loaded = true;
      fixtureSession = result.source === "fixture";
      if (result.source === "live" && result.data.some((world) => world.sample !== true && world.access !== "team")) {
        realSeen = true;
      }
      noteAdded();
      publish(result.source === "fixture" || !realSeen);
    },
    fail(ticket: number) {
      if (ticket !== generation) return;
      loaded = true;
      publish(false);
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      stop ??= store.subscribe(noteAdded);
      noteAdded();
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) {
          stop?.();
          stop = undefined;
        }
      };
    },
    load() {
      if (loaded || pending || realSeen) return;
      pending = true;
      const ticket = generation;
      const state = store.getState();
      void api
        .getWorlds(state.dec, state.added)
        .catch(() => {
          if (ticket !== generation) return;
          loaded = true;
          publish(false);
        })
        .finally(() => {
          if (ticket === generation) pending = false;
        });
    },
    dispose() {
      // Cancels stale reads; permits React's effect replay to subscribe/load again.
      generation++;
      loaded = demo;
      pending = false;
      stop?.();
      stop = undefined;
      listeners.clear();
    },
  };
}

export type FirstRun = ReturnType<typeof createFirstRun>;
