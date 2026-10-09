// Loading, empty and error handling for every TiloClient call a flow screen makes (PRD 18.4
// error rule: what happened, what Tilo did, what is next). Nothing here ever rejects unhandled
// or logs to the console.
import { useCallback, useEffect, useRef, useState } from "react";
import { describeError } from "../api/describeError";
import { TiloApiError, isLifetimeCap } from "../api/http";
import { useNavigate } from "../router";

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

export interface Action {
  readonly busy: boolean;
  readonly error: string | null;
  /** The failed start was the replay-only label: show the banner, not `error`. */
  readonly replayOnly?: boolean;
  /** SEC-16: the failed start was the lifetime allowance: show the pop-up, not `error`. */
  readonly lifetimeCap?: boolean;
  readonly go: () => void;
}

/** The primary button's action: busy at once (synchronously, UX-2), then navigates to the path
 * `run` resolves with. A rejection becomes `error` and the button is usable again. */
export function useAction(doing: string, run: () => Promise<string | null>): Action {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replayOnly, setReplayOnly] = useState(false);
  const [lifetimeCap, setLifetimeCap] = useState(false);
  const busyRef = useRef(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  const runRef = useRef(run);
  runRef.current = run;

  const go = useCallback(() => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    setReplayOnly(false);
    setLifetimeCap(false);
    const hold = new Promise<void>((resolve) => setTimeout(resolve, PRESS_MS));
    // Failure waits out the press too, so the busy feedback is never a flicker.
    const outcome = Promise.resolve()
      .then(() => runRef.current())
      .then(
        (to) => ({ to }),
        (e: unknown) => ({ e }),
      );
    void Promise.all([outcome, hold]).then(([result]) => {
      if ("to" in result) {
        if (result.to === null) {
          // The call did what it was asked and the screen stays to say more (S-03's weekly repeat).
          busyRef.current = false;
          if (live.current) setBusy(false);
        } else if (live.current) navigate(result.to); // the next screen mounts fresh, so busy resets
        return;
      }
      busyRef.current = false;
      if (!live.current) return;
      setBusy(false);
      setError(describeError(doing, result.e));
      setReplayOnly(isReplayOnly(result.e));
      setLifetimeCap(isLifetimeCap(result.e));
    });
  }, [doing, navigate]);

  return { busy, error, replayOnly, lifetimeCap, go };
}
