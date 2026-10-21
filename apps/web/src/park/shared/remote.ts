// Loading, empty and error handling for every TiloClient call a flow screen makes (PRD 18.4
// error rule: what happened, what Tilo did, what is next). Nothing here ever rejects unhandled
// or logs to the console.
import { useCallback, useEffect, useRef, useState } from "react";
import { describeError } from "../../api/describeError";
import { TiloApiError, isLifetimeCap } from "../../api/http";

export type Remote<T> =
  | { readonly status: "loading" }
  | {
      readonly status: "error";
      readonly message: string;
      readonly replayOnly?: boolean;
      /** SEC-16: the failure is the lifetime allowance (403 `spend_cap_reached`): the pop-up replaces the error. */
      readonly lifetimeCap?: boolean;
    }
  | { readonly status: "ready"; readonly value: T };

/** UX-2 / PRD 18.2: the 120 ms press. Busy feedback is held at least this long. */
export const PRESS_MS = 120;

/** NFR-22: the failure is the replay-only label (live models unavailable), shown as the banner. */
export const isReplayOnly = (error: unknown): boolean =>
  error instanceof TiloApiError && error.replayOnly;

export { describeError }; // moved to api/ so the Park forms share it

/** Runs `load` on mount and on every retry; its signal aborts when the screen unmounts or reloads. While `enabled` is false nothing is requested and the
 * state stays "loading" (a call that can only fail until something is on record, such as the
 * delivery of a run that has not completed, is not made at all: the browser logs each refusal). */
export function useRemote<T>(
  doing: string,
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
): readonly [Remote<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Remote<T>>({ status: "loading" });
  const loadRef = useRef(load);
  loadRef.current = load;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the retry trigger.
  useEffect(() => {
    let live = true;
    const stop = new AbortController();
    setState({ status: "loading" });
    if (!enabled) return;
    Promise.resolve()
      .then(() => loadRef.current(stop.signal))
      .then(
        (value) => live && setState({ status: "ready", value }),
        (e: unknown) =>
          live &&
          setState({
            status: "error",
            message: describeError(doing, e),
            replayOnly: isReplayOnly(e),
            lifetimeCap: isLifetimeCap(e),
          }),
      );
    return () => {
      live = false;
      stop.abort(); // a call that waits on the server (getLayout) stops with the page
    };
  }, [attempt, doing, enabled]);
  return [state, useCallback(() => setAttempt((n) => n + 1), [])];
}
