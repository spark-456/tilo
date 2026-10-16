// TILO-T-WORLD: "Convene team": a person calls a Lead (or the Director) and up to ROOM_MAX_AGENTS of its agents into the
// Meeting Hall, asks them what they did and why, and can ask them to change direction. It is the existing meeting
// room (ADR-0028): the stage walks them to the hall on meeting.convened and back on meeting.adjourned (events, not
// this component); a change is only ever the confirmation of a proposal an agent made in a reply (MR-07).
import type { Event } from "@tilo/contracts";
import { useMemo, useState } from "react";
import { Buddy, Icon } from "../../design/tilo-t";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { ROOM_MAX_AGENTS, type Seat, teamSeat } from "../../park/api/live/roomTalk";
import type { AgentStats } from "../../world/agentStats";
import type { WorldFacts } from "../../world/useWorldFacts";
import { RoomThread } from "./RoomThread";
import { MOOD_OF_STATUS, roleOf } from "./agentLook";
import "./live.css";

export function TeamMeeting({
  worldId,
  facts,
  events,
  rooms,
  onClose,
}: {
  worldId: string;
  facts: WorldFacts;
  events: readonly Event[];
  rooms: RoomClient | null;
  onClose: () => void;
}) {
  const layout = facts.layout;
  const heads = useMemo(
    () => (layout?.semantic.agents ?? []).filter((a) => a.rank === "director" || a.rank === "lead"),
    [layout],
  );
  const [lead, setLead] = useState(heads.find((a) => a.rank === "lead")?.id ?? heads[0]?.id ?? "");
  const [picked, setPicked] = useState<string[]>([]);
  const [seat, setSeat] = useState<Seat | null>(null);
  // Who the API would seat with this lead (its district's workers, or the Director's Leads), from the layout.
  const eligible = useMemo(() => {
    if (!layout) return [];
    const all = layout.semantic.agents.map((a) => a.id);
    return teamSeat(layout, events, lead, all)?.agents ?? [];
  }, [layout, events, lead]);
  const chosen = picked.filter((id) => eligible.includes(id)).slice(0, ROOM_MAX_AGENTS);
  const stat = (id: string) => facts.stats.get(id);

  if (seat) {
    const members = [seat.lead, ...seat.agents]
      .map(stat)
      .filter((s): s is AgentStats => s !== undefined);
    return (
      <aside className="tw-panel tw-slide-r" data-testid="team-meeting" aria-label="Team meeting">
        <header className="tw-panel__head">
          <div>
            <h2 className="tw-panel__name">Team meeting</h2>
            <p className="tw-card__role">
              {members.map((s) => s.name).join(", ")} in the Meeting Hall
            </p>
          </div>
          <button type="button" className="tw-panel__x" aria-label="Close" onClick={onClose}>
            <Icon name="x" size={20} />
          </button>
        </header>
        <div className="tw-team__row">
          {members.map((s) => (
            <Buddy key={s.id} size={44} role={roleOf(s.rank)} mood={MOOD_OF_STATUS[s.status]} />
          ))}
        </div>
        <RoomThread
          client={rooms}
          worldId={worldId}
          seat={seat}
          events={events}
          stats={members}
          heading="Ask the team"
          defaultTo={seat.lead}
          changeAsk
          autoConvene
        />
      </aside>
    );
  }
  return (
    <aside className="tw-panel tw-slide-r" data-testid="team-meeting" aria-label="Convene team">
      <header className="tw-panel__head">
        <div>
          <h2 className="tw-panel__name">Convene team</h2>
          <p className="tw-card__role">Call agents into the Meeting Hall and talk with them.</p>
        </div>
        <button type="button" className="tw-panel__x" aria-label="Close" onClick={onClose}>
          <Icon name="x" size={20} />
        </button>
      </header>
      {heads.length === 0 ? (
        <p className="tw-room__off">This world has no Lead to call yet.</p>
      ) : (
        <form
          className="tw-team__form"
          onSubmit={(e) => {
            e.preventDefault();
            setSeat({ lead, agents: chosen });
          }}
        >
          <label>
            <span>Who leads the meeting</span>
            <select
              value={lead}
              onChange={(e) => {
                setLead(e.target.value);
                setPicked([]);
              }}
            >
              {heads.map((a) => (
                <option key={a.id} value={a.id}>
                  {facts.names.get(a.id) ?? a.id}
                </option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>Invite up to {ROOM_MAX_AGENTS} agents</legend>
            {eligible.length === 0 ? (
              <p className="tw-card__quiet">Nobody else can join this lead's meeting yet.</p>
            ) : (
              eligible.map((id) => (
                <label key={id} className="tw-team__pick">
                  <input
                    type="checkbox"
                    checked={chosen.includes(id)}
                    disabled={!chosen.includes(id) && chosen.length >= ROOM_MAX_AGENTS}
                    onChange={(e) =>
                      setPicked(e.target.checked ? [...chosen, id] : chosen.filter((x) => x !== id))
                    }
                  />
                  {facts.names.get(id) ?? id}
                </label>
              ))
            )}
          </fieldset>
          <button type="submit" className="tw-team__go" disabled={!rooms}>
            Convene
          </button>
          {rooms ? null : (
            <p className="tw-room__off">
              Meetings need the live Tilo service, which this view is not connected to.
            </p>
          )}
        </form>
      )}
    </aside>
  );
}
