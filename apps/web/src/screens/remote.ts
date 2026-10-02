// Loading, empty and error handling for every TiloClient call a flow screen makes (PRD 18.4
// error rule: what happened, what Tilo did, what is next). Nothing here ever rejects unhandled
// or logs to the console.
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "../router";

export type Remote<T> =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly value: T };

/** UX-2 / PRD 18.2: the 120 ms press. Busy feedback is held at least this long. */
export const PRESS_MS = 120;

export function describeError(doing: string, error: unknown): string {
  const reason = error instanceof Error && error.message ? error.message : "an unknown error";
  return `Could not ${doing}: ${reason}. Nothing was changed. You can try again.`;
}

/** Runs `load` on mount and on every retry. */
export function useRemote<T>(
  doing: string,
  load: () => Promise<T>,
): readonly [Remote<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Remote<T>>({ status: "loading" });
  const loadRef = useRef(load);
  loadRef.current = load;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the retry trigger.
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    Promise.resolve()
      .then(() => loadRef.current())
      .then(
        (value) => live && setState({ status: "ready", value }),
        (e: unknown) => live && setState({ status: "error", message: describeError(doing, e) }),
      );
    return () => {
      live = false;
    };
  }, [attempt, doing]);
  return [state, useCallback(() => setAttempt((n) => n + 1), [])];
}

export interface Action {
  readonly busy: boolean;
  readonly error: string | null;
  readonly go: () => void;
}

/** The primary button's action: busy at once (synchronously, UX-2), then navigates to the path
 * `run` resolves with. A rejection becomes `error` and the button is usable again. */
export function useAction(doing: string, run: () => Promise<string>): Action {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
        if (live.current) navigate(result.to); // the next screen mounts fresh, so busy resets
        return;
      }
      busyRef.current = false;
      if (!live.current) return;
      setBusy(false);
      setError(describeError(doing, result.e));
    });
  }, [doing, navigate]);

  return { busy, error, go };
}
