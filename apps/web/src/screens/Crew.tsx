// The crew of a world on S-14's hero card (artboard "Tilo Worlds": the agents standing on the
// card): every agent of the layout, drawn as in the thumbnail (same figure, same rank mark), with
// its name and whether the recorded run has brought it in yet (HR-1). One that has not joined is
// faded and says so in words ("Not joined"), so state never rests on the figure alone.
import type { Event, Layout } from "@tilo/contracts";
import tokens from "../design/tokens";
import { frameOf } from "../world/frame";
import type { WorldState } from "../world/reducer";
import { agentNames } from "../world/runSummary";
import { AgentFigure } from "./WorldThumb";

export function Crew({
  layout,
  state,
  events,
}: { layout: Layout; state: WorldState; events: readonly Event[] }) {
  const names = agentNames(layout);
  const acted = new Set(events.map((e) => e.actor)); // as the HUD team list: spawned, or has acted
  const tints = new Map(frameOf(layout, state).agents.map((a) => [a.id, a.tint]));
  return (
    <ul className="crew" aria-label="The team" data-testid="crew">
      {layout.semantic.agents.map((a) => {
        const joined = state.agents[a.id]?.spawned === true || acted.has(a.id);
        return (
          <li key={a.id} data-joined={joined}>
            <svg viewBox="-14 -40 28 46" aria-hidden="true" focusable="false">
              <AgentFigure rank={a.rank} tint={tints.get(a.id) ?? tokens.color.ink["3"]} />
            </svg>
            <span className="crew-name">{names.get(a.id)}</span>
            <span className="crew-state">{joined ? "" : "Not joined"}</span>
          </li>
        );
      })}
    </ul>
  );
}
