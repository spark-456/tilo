import { useCallback, useEffect, useRef, useState } from "react";
import { describeError } from "./describeError";
import { TiloApiError, isLifetimeCap } from "./http";
export { useRunLog } from "../world/runLog";
export { worldStatus } from "../world/runSummary";
export { useRunWorld } from "../world/worldContext";

type Remote<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; message: string; replayOnly: boolean; lifetimeCap: boolean };

// Ported from screens/remote: abort on unmount, safe NFR-22 messages, read-only retries.
export function useAdminRead<T>(
  doing: string,
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
): readonly [Remote<T>, () => void] {
  const [attempt, retry] = useState(0);
  const [state, setState] = useState<Remote<T>>({ status: "loading" });
  const latest = useRef(load);
  latest.current = load;
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt triggers a fresh read.
  useEffect(() => {
    let live = true;
    const stop = new AbortController();
    setState({ status: "loading" });
    if (!enabled) return;
    Promise.resolve()
      .then(() => latest.current(stop.signal))
      .then(
        (value) => live && setState({ status: "ready", value }),
        (error: unknown) =>
          live &&
          setState({
            status: "error",
            message: describeError(doing, error),
            replayOnly: error instanceof TiloApiError && error.replayOnly,
            lifetimeCap: isLifetimeCap(error),
          }),
      );
    return () => {
      live = false;
      stop.abort();
    };
  }, [attempt, doing, enabled]);
  return [state, useCallback(() => retry((value) => value + 1), [])];
}
