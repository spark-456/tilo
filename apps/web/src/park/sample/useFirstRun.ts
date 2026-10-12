import { useEffect, useSyncExternalStore } from "react";
import { useFirstRunController } from "../app/context";

/** True only for a demo session or a successful worlds read with no personal world. */
export function useFirstRun(): boolean {
  const firstRun = useFirstRunController();
  const first = useSyncExternalStore(firstRun.subscribe, firstRun.getState);
  useEffect(() => firstRun.load(), [firstRun]);
  return first;
}
