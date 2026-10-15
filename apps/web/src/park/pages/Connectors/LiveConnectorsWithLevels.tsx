// STUDIO-WIRE-1 (FR-ACC-01): each app's access level on the live list, read from GET /v1/team `tools[].level`.
// That route is the Owner's, so it is asked only once GET /v1/people says the signed-in person is an Owner; anyone
// else is told who sets the level and no refused request is made. Anything unreadable stays "not available yet".
// CONNECTORS-DESIGN: the Owner changes a level in the manage panel through the same PUT the Team page uses
// (api.writeTeam, `tool` op): optimistic, rolled back with the server's own sentence when it fails.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "../../api";
import { type TeamView, teamErrorText } from "../../api/live/teamLive";
import type { ToolLevels } from "./LiveConnectors";

const known = (view: TeamView): ToolLevels => ({
  kind: "known",
  byId: Object.fromEntries(view.tools.map((t) => [t.connector, t.level])),
});

export interface LevelControl {
  levels: ToolLevels;
  /** The last save failure, or empty. */
  failure: string;
  busy: boolean;
  /** Owner only: resolves true once the server accepted it. */
  setLevel: (connector: string, level: string) => Promise<boolean>;
}

export function useToolLevels(api: Api): LevelControl {
  const [levels, setLevels] = useState<ToolLevels>({ kind: "loading" });
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const locked = useRef(false);
  useEffect(() => {
    alive.current = true;
    const set = (next: ToolLevels) => alive.current && setLevels(next);
    api
      .getTeam()
      .then(async ({ data }) => {
        const me = data.people.find((p) => p.you);
        if (!me?.role) return set({ kind: "unknown" });
        if (me.role !== "Owner") return set({ kind: "not_owner" });
        const { data: view } = await api.getTeamLive();
        set(view ? known(view) : { kind: "unknown" });
      })
      .catch(() => set({ kind: "unknown" }));
    return () => {
      alive.current = false;
    };
  }, [api]);

  const setLevel = useCallback(
    async (connector: string, level: string) => {
      if (levels.kind !== "known" || locked.current) return false;
      const before = levels;
      locked.current = true;
      setBusy(true);
      setFailure("");
      setLevels({ kind: "known", byId: { ...before.byId, [connector]: level } });
      try {
        const r = await api.writeTeam({ kind: "tool", connector, level });
        if (alive.current && r.data) setLevels(known(r.data));
        return true;
      } catch (e) {
        if (alive.current) {
          setLevels(before);
          setFailure(teamErrorText(e));
        }
        return false;
      } finally {
        locked.current = false;
        if (alive.current) setBusy(false);
      }
    },
    [api, levels],
  );
  return { levels, failure, busy, setLevel };
}
