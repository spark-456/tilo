// FR-WLD-07 (web side): Pause all is a request. Nothing here says the world is paused: the veil,
// the "Paused" banner and the paused status come only from a recorded world.paused event (PRD 9.4
// HR-1) and lift only on world.resumed. Until the event the person sees "Pausing…", and after a
// bounded wait "No confirmation recorded yet" (the same rule as a Needs-you answer).
import { useCallback, useEffect, useRef, useState } from "react";
import type { TiloClient } from "../api/client";
import { describeError } from "../screens/remote";
import { type RunStatus, runEnded } from "./runSummary";

/** How long a sent request waits for world.paused before the control says nothing came back.
 * The product promise is 2 s (NFR-07); this leaves room for a slow network and stays bounded. */
export const PAUSE_CONFIRM_MS = 5000;

/** A client that can send Pause all. `pauseWorld` is not on the frozen TiloClient interface (it is
 * on HttpClient and FixtureClient), so it is detected here, never added there. */
export interface PausableClient extends TiloClient {
  pauseWorld(worldId: string): Promise<void>;
}

export const canPause = (client: TiloClient): client is PausableClient =>
  typeof (client as Partial<PausableClient>).pauseWorld === "function";

/** What the Pause all slot shows. Only "paused" is ever claimed, and only from the recorded status. */
export type PauseView =
  | "ready"
  | "pausing"
  | "unconfirmed"
  | "error"
  | "unavailable"
  | "paused"
  | "ended";

type Request = "none" | "pausing" | "unconfirmed" | "error";

export function pauseView(status: RunStatus, request: Request, available: boolean): PauseView {
  if (status === "paused") return "paused";
  if (runEnded(status)) return "ended";
  if (!available) return "unavailable";
  return request === "none" ? "ready" : request;
}

export interface PauseControl {
  readonly view: PauseView;
  readonly error: string | null;
  readonly pause: () => void;
}

/** Sends Pause all through the client. `status` is the run's recorded status: the request settles
 * only when it becomes "paused"; a rejection shows its error; silence ends as "unconfirmed". */
export function usePause(
  client: TiloClient,
  worldId: string,
  status: RunStatus,
  confirmMs = PAUSE_CONFIRM_MS,
): PauseControl {
  const [request, setRequest] = useState<Request>("none");
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const live = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const statusRef = useRef(status);
  statusRef.current = status;
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      clearTimeout(timer.current);
    };
  }, []);
  // The recorded event is what settles the request (HR-1).
  useEffect(() => {
    if (status !== "paused") return;
    clearTimeout(timer.current);
    busy.current = false;
    setRequest("none");
  }, [status]);

  const pause = useCallback(() => {
    if (busy.current || !canPause(client)) return;
    busy.current = true;
    clearTimeout(timer.current);
    setRequest("pausing");
    setError(null);
    Promise.resolve()
      .then(() => client.pauseWorld(worldId))
      .then(() => {
        if (statusRef.current === "paused") return; // the event beat the response: already settled
        timer.current = setTimeout(() => {
          busy.current = false;
          if (live.current) setRequest("unconfirmed");
        }, confirmMs);
      })
      .catch((e: unknown) => {
        busy.current = false;
        if (!live.current) return;
        setRequest("error");
        setError(describeError("pause all work", e));
      });
  }, [client, worldId, confirmMs]);

  return { view: pauseView(status, request, canPause(client)), error, pause };
}
