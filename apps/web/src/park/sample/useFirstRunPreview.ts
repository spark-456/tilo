import { useSyncExternalStore } from "react";
import { useParkStore } from "../app/context";
import { useFirstRun } from "./useFirstRun";

/** The existing demo UI keeps its behavior; previews are for empty HTTP accounts. */
export function useFirstRunPreview(): boolean {
  const store = useParkStore();
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const live = state.sources.live && !state.sources.fixture;
  // Fixture pages cannot show this preview, so they need no eligibility read.
  const first = useFirstRun(live);
  return first && live;
}
