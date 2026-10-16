// TILO-T-WORLD: an agent's own panel, opened by clicking it on the stage: who it is, what it is doing, and "Talk to
// <agent>" - a 1:1 room through the meeting-room API. Its memory of its own is its recorded work in this world: the
// lines it said and was told (listed here from the same events), and the same record the room's reply is grounded in
// (meeting_room_reply.ground: its own events, never another agent's, never room talk). Display state only.
import type { Event } from "@tilo/contracts";
import { useMemo } from "react";
import { Buddy, Icon } from "../../design/tilo-t";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { seatFor } from "../../park/api/live/roomTalk";
import type { AgentStats } from "../../world/agentStats";
import type { WorldFacts } from "../../world/useWorldFacts";
import { AgentFacts } from "./AgentCard";
import { RoomThread } from "./RoomThread";
import { MOOD_OF_STATUS, clock, roleOf } from "./agentLook";
import "./live.css";

const REMEMBERED = 6;

export function AgentPanel({
  worldId,
  stats,
  facts,
  events,
  rooms,
  onClose,
}: {
  worldId: string;
  stats: AgentStats;
  facts: WorldFacts;
  events: readonly Event[];
  rooms: RoomClient | null;
  onClose: () => void;
}) {
  const layout = facts.layout;
  const seat = useMemo(
    () => (layout ? seatFor(layout, events, stats.id) : null),
    [layout, events, stats.id],
  );
  // The room lists its lead first; the person asks the agent they opened.
  const inRoom = useMemo(() => {
    if (!seat) return [];
    return [seat.lead, ...seat.agents]
      .map((id) => facts.stats.get(id))
      .filter((s): s is AgentStats => s !== undefined);
  }, [seat, facts.stats]);
  const mine = facts.messages
    .filter((m) => (m.from === stats.id || m.to === stats.id) && m.text)
    .slice(-REMEMBERED);
  const first = events[0]?.ts;
  const name = (id: string) => facts.names.get(id) ?? "You";
  return (
    <aside className="tw-panel tw-slide-r" data-testid="agent-panel" aria-label={`${stats.name}`}>
      <header className="tw-panel__head">
        <Buddy mood={MOOD_OF_STATUS[stats.status]} role={roleOf(stats.rank)} size={64} />
        <div>
          <h2 className="tw-panel__name">{stats.name}</h2>
          <p className="tw-card__role">
            {stats.role}
            {stats.district ? ` · ${stats.district}` : ""}
          </p>
        </div>
        <button type="button" className="tw-panel__x" aria-label="Close" onClick={onClose}>
          <Icon name="x" size={20} />
        </button>
      </header>
      <AgentFacts stats={stats} />
      <section className="tw-panel__mem" aria-label="What it remembers">
        <h3 className="tw-room__h">What it remembers of this world</h3>
        {mine.length === 0 ? (
          <p className="tw-card__quiet">Nothing recorded for it yet.</p>
        ) : (
          <ul>
            {mine.map((m) => (
              <li key={m.seq}>
                <time>{clock(first, m.ts)}</time> {m.from === stats.id ? "said to" : "heard from"}{" "}
                {name(m.from === stats.id ? m.to : m.from)}: {m.text}
              </li>
            ))}
          </ul>
        )}
      </section>
      <RoomThread
        key={stats.id}
        client={rooms}
        worldId={worldId}
        seat={seat}
        events={events}
        stats={inRoom}
        heading={`Talk to ${stats.name}`}
        defaultTo={stats.id}
        changeAsk
      />
    </aside>
  );
}
