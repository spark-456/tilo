// STUDIO-WIRE-1 (FR-ACC-01): each app's access level on the live list, read from GET /v1/team `tools[].level`.
// That route is the Owner's, so it is asked only once GET /v1/people says the signed-in person is an Owner; anyone
// else is told who sets the level and no refused request is made. Anything unreadable stays "not available yet".
import { useEffect, useState } from "react";
import type { Api } from "../../api";
import type { Connector } from "../../api/types";
import { LiveConnectors, type ToolLevels } from "./LiveConnectors";

export function LiveConnectorsWithLevels({
  api,
  connectors,
}: { api: Api; connectors: Connector[] }) {
  const [levels, setLevels] = useState<ToolLevels>({ kind: "loading" });
  useEffect(() => {
    let alive = true;
    const set = (next: ToolLevels) => alive && setLevels(next);
    api
      .getTeam()
      .then(async ({ data }) => {
        const me = data.people.find((p) => p.you);
        if (!me?.role) return set({ kind: "unknown" });
        if (me.role !== "Owner") return set({ kind: "not_owner" });
        const { data: view } = await api.getTeamLive();
        set(
          view
            ? {
                kind: "known",
                byId: Object.fromEntries(view.tools.map((t) => [t.connector, t.level])),
              }
            : { kind: "unknown" },
        );
      })
      .catch(() => set({ kind: "unknown" }));
    return () => {
      alive = false;
    };
  }, [api]);
  return <LiveConnectors connectors={connectors} levels={levels} />;
}
