// What the Inspect panel adds for a building or an agent (PRD 18.3, #227 E3): a few plain facts and
// the tone of its state chip. Every fact is read from the layout or the reducer over the recorded
// events (HR-1); nothing is guessed, and a fact the run has not recorded says so.
import type { Layout } from "@tilo/contracts";
import { findItem } from "../world/findItem";
import type { WorldState } from "../world/reducer";
import { agentNames, rankName } from "../world/runSummary";
import { words } from "./text";

export type Fact = readonly [label: string, value: string];

/** The tone of a state's chip: a finished thing is `done`, a thing not started yet is `soon` (a
 * dashed outline, so the state differs by shape as well as colour), the rest is in progress. */
export function stateTone(state: string): "done" | "soon" | "blocked" | "fyi" {
  if (/^(Finished|Delivered)/.test(state)) return "done";
  if (/^(Planned|Not |Locked|Waiting)/.test(state)) return "soon";
  if (/^Connection lost/.test(state)) return "blocked";
  return "fyi";
}

/** At most three names, then "and N more": a value of a bounded length, so the facts block keeps
 * its height as events arrive (CLS). */
const list = (names: readonly string[]): string =>
  names.length <= 3
    ? names.join(", ")
    : `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;

export function factsOf(layout: Layout, id: string, state: WorldState): Fact[] {
  const names = agentNames(layout);
  const building = layout.semantic.levels
    .flatMap((l) => l.districts.flatMap((d) => d.buildings))
    .find((b) => b.id === id);
  if (building) {
    const here = Object.values(state.agents)
      .filter((a) => a.spawned && a.location === id)
      .map((a) => names.get(a.id) ?? a.id);
    return [
      ["Kind", building.common_type ? words(building.common_type) : "Built for this task"],
      ["People here", here.length > 0 ? list(here) : "Nobody has been sent here yet"],
    ];
  }
  const agent = layout.semantic.agents.find((a) => a.id === id);
  if (agent) {
    const at = state.agents[id]?.location;
    return [
      ["Role", rankName(agent.rank)],
      [
        "Reports to",
        agent.team_lead
          ? (names.get(agent.team_lead) ?? agent.team_lead)
          : "Nobody: leads the team",
      ],
      ["Now at", at ? (findItem(layout, at)?.name ?? "Not placed yet") : "Not placed yet"],
    ];
  }
  return [];
}
