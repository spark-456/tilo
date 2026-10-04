// S-15 Stop all autopilot (PRD 10.4, FR-HIL-07): one request that puts every one of the person's
// rules back at level L1, so each action waits for them again. The page claims nothing before the
// API answers, and then only what the answer says (HR-1): how many rules it stopped, how many
// were already at L1, and which channels it confirms on. Nothing here is optimistic.
import { useCallback, useEffect, useRef, useState } from "react";
import type { TiloClient } from "../api/client";
import { type StopResult, isStopResult } from "../api/stop";
import { describeError } from "../screens/remote";

/** A client that can send the stop. Like `pauseWorld` it is not on the frozen TiloClient
 * interface (it is on HttpClient and FixtureClient), so it is detected here, never added there. */
export interface StoppableClient extends TiloClient {
  stopAutopilot(worldId: string): Promise<StopResult>;
}

export const canStopAutopilot = (client: TiloClient): client is StoppableClient =>
  typeof (client as Partial<StoppableClient>).stopAutopilot === "function";

const rules = (n: number): string => `${n} ${n === 1 ? "rule" : "rules"}`;

/** What the person is told, from the API's answer alone. */
export function describeStop(r: StopResult): string {
  const parts: string[] = [];
  if (r.stopped === 0 && r.already_l1 === 0) {
    parts.push("No rule was running on its own, so nothing needed stopping.");
  } else {
    if (r.stopped > 0)
      parts.push(`Stopped ${rules(r.stopped)}: each now waits for you at level L1.`);
    if (r.already_l1 > 0) parts.push(`${rules(r.already_l1)} already waited for you.`);
  }
  if (r.pending > 0) {
    // With nothing stopped here, the pending changes are not ours to count: say they are others.
    parts.push(
      r.stopped === 0
        ? "Other changes are still being recorded."
        : `${r.pending} ${r.pending === 1 ? "change is" : "changes are"} still being recorded.`,
    );
  }
  return parts.join(" ");
}

export type StopView = "ready" | "confirming" | "sending" | "done" | "error";

export interface StopControl {
  readonly view: StopView;
  readonly result: StopResult | null;
  readonly error: string | null;
  readonly ask: () => void;
  readonly cancel: () => void;
  readonly confirm: () => void;
}

/** The stop in three steps: ask (nothing is sent), confirm (sends once), then the answer. State
 * belongs to one world: another world starts again from "ready". */
export function useStopAutopilot(client: TiloClient, worldId: string): StopControl {
  const [view, setView] = useState<StopView>("ready");
  const [result, setResult] = useState<StopResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  const live = useRef(true);
  // biome-ignore lint/correctness/useExhaustiveDependencies: worldId is the key: a new world starts again.
  useEffect(() => {
    live.current = true;
    setView("ready");
    setResult(null);
    setError(null);
    return () => {
      live.current = false;
    };
  }, [worldId]);

  const confirm = useCallback(() => {
    if (sending.current || !canStopAutopilot(client)) return;
    sending.current = true;
    setView("sending");
    setError(null);
    client
      .stopAutopilot(worldId)
      .then((r) => {
        if (!live.current) return;
        if (!isStopResult(r)) throw new Error("Tilo sent a reply this page could not read");
        setResult(r);
        setView("done");
      })
      .catch((e: unknown) => {
        if (!live.current) return;
        setError(describeError("stop all autopilot", e));
        setView("error");
      })
      .finally(() => {
        sending.current = false;
      });
  }, [client, worldId]);

  return {
    view,
    result,
    error,
    ask: () => setView("confirming"),
    cancel: () => setView("ready"),
    confirm,
  };
}
