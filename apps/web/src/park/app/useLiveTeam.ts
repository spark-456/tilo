// TEAM-WEB (FR-TEAM-02/04, FR-ACC-01): the live team state machine shared by the Team and Connectors pages
// (kept outside both, so neither imports the other). It reads GET /v1/team through api.getTeamLive and sends each
// Owner-only write through api.writeTeam: optimistic, rolled back on failure, refetched on a stale write (409),
// one write at a time.
import { useCallback, useEffect, useRef, useState } from "react";
import { TiloApiError } from "../../api/http";
import type { Api } from "../api";
import {
  type TeamOp,
  type TeamView,
  applyOp,
  isStale,
  readErrorText,
  teamErrorText,
} from "../api/live/teamLive";
import { NotBuilt } from "../api/liveApi";

export type LiveState =
  | { phase: "probing" }
  | { phase: "fixture" }
  | { phase: "error"; text: string }
  | { phase: "ready"; view: TeamView };

export interface LiveTeam {
  state: LiveState;
  /** The line under the heading: the last failure, else why the controls are off. Always present, so nothing shifts. */
  note: string;
  busy: boolean;
  isOwner: boolean;
  send: (op: TeamOp) => Promise<boolean>;
}

export const REFRESH_FAILED = "Saved; could not refresh";
export const READ_ONLY = "Only an Owner can change the team. You can look at it.";
export const isNotBuilt = (e: unknown): boolean => e instanceof NotBuilt;

export function useLiveTeam(api: Api): LiveTeam {
  const [state, setState] = useState<LiveState>({ phase: "probing" });
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    api.getTeamLive().then(
      (r) =>
        alive.current && setState(r.data ? { phase: "ready", view: r.data } : { phase: "fixture" }),
      // A TiloApiError means a live server answered; anything else (NotBuilt) is the sample path's to handle.
      (e: unknown) =>
        alive.current &&
        setState(
          e instanceof TiloApiError
            ? { phase: "error", text: readErrorText(e) }
            : { phase: "fixture" },
        ),
    );
    return () => {
      alive.current = false;
    };
  }, [api]);

  const view = state.phase === "ready" ? state.view : null;
  const send = useCallback(
    async (op: TeamOp): Promise<boolean> => {
      if (!view || locked.current) return false;
      locked.current = true;
      setBusy(true);
      setFailure("");
      const show = (v: TeamView) => alive.current && setState({ phase: "ready", view: v });
      show(applyOp(view, op));
      try {
        const r = await api.writeTeam(op);
        if (r.data) show(r.data);
        // An invite saved but the follow-up read failed: keep the optimistic state; a retry would be refused.
        else if (op.kind === "invite" && alive.current) setFailure(REFRESH_FAILED);
        return true;
      } catch (e) {
        show(view); // roll back
        if (alive.current) setFailure(teamErrorText(e));
        if (isStale(e)) {
          const fresh = await api.getTeamLive().catch(() => null);
          if (fresh?.data) show(fresh.data);
        }
        return false;
      } finally {
        locked.current = false;
        if (alive.current) setBusy(false);
      }
    },
    [api, view],
  );
  const isOwner = view?.me.role === "Owner";
  return { state, note: failure || (view && !isOwner ? READ_ONLY : ""), busy, isOwner, send };
}
