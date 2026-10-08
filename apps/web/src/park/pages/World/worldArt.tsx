// The pictures of the World page, from the Park render kit the shell shares (one kit per document, so the
// agents and buildings the shell drew are not drawn again). The city map is drawn from the plan the Api
// returned, not from a copy held in the kit.
import type { ReactNode } from "react";
import type { Dec, Plan, World } from "../../api/types";
import type { AgentSpec } from "../../engines/types";
import { cachedCity } from "../../shell/cityCache";
import { parkKit } from "../../shell/kit";
import { keyed } from "./worldModel";

export const agentArt = (spec: AgentSpec, size: number, night: boolean): ReactNode =>
  parkKit().agent(spec, size, night) as ReactNode;

/** The city map for a plan. The plan already holds the decisions that are on, so the picture is kept by the plan's
 * content and the time of day (FR-UX-12); the Worlds card of the same city shares it. */
export function cityArt(plan: Plan, _planId: string, _dec: Dec, night: boolean): ReactNode {
  return cachedCity(plan, night, (p, n) => parkKit().TP.world(p, { night: n }) as ReactNode);
}

/** A Town's row of buildings, drawn side by side, each tucked 40px under the one before. */
export function rowArt(row: NonNullable<World["row"]>, night: boolean): ReactNode {
  const kit = parkKit();
  const name = (b: NonNullable<World["row"]>[number]): string =>
    `${typeof b[0] === "string" ? b[0] : b[0].i}|${b[1]}|${b[2]}`;
  return keyed(row, name).map(([key, b], i) => (
    <div key={key} className="park-world-rowitem" style={{ marginLeft: i ? -40 : 0 }}>
      {kit.building(b[0], b[1], b[2], 200, night) as ReactNode}
    </div>
  ));
}

/** A Village's single building (or the first of a row) at the size of the map. */
export const singleArt = (w: World, night: boolean): ReactNode =>
  parkKit().art(w, 220, night) as ReactNode;
