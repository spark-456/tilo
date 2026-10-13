import { useSyncExternalStore } from "react";
import { useParkStore } from "../app/context";
import { useFirstRun } from "./useFirstRun";

/** The existing demo UI keeps its behavior; previews are for empty HTTP accounts. */
export function useFirstRunPreview(loadWorlds = true): boolean {
  const first = useFirstRun(loadWorlds);
  const store = useParkStore();
  const state = useSyncExternalStore(store.subscribe, store.getState);
  return first && state.sources.live && !state.sources.fixture;
}
