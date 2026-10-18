// TILO-T-WORLD: an agent's own panel, opened by clicking it on the stage: who it is, what it is doing, and "Talk to
// <agent>" - a 1:1 room through the meeting-room API. Its memory of its own is its recorded work in this world: the
// lines it said and was told (listed here from the same events), and the same record the room's reply is grounded in
// (meeting_room_reply.ground: its own events, never another agent's, never room talk). Display state only.
import type { Event } from "@tilo/contracts";
import { useMemo } from "react";
import { Icon } from "../../design/tilo-t";
import { AgentSprite, agentColorByOrder, agentColorNameByOrder } from "../../design/tilo-w";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { seatFor } from "../../park/api/live/roomTalk";
import type { AgentStats } from "../../world/agentStats";
import type { WorldFacts } from "../../world/useWorldFacts";
import { AgentFacts } from "./AgentCard";
import { RoomThread } from "./RoomThread";
import { clock, spriteKindOfRank, spriteMoodOfStatus } from "./agentLook";
import { agentMessageText } from "./agentMessageText";
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
  const col = agentColorByOrder(stats.order);
  const colName = agentColorNameByOrder(stats.order);

  return (
    <aside
      className="tw-panel tw-agent-panel"
      data-testid="agent-panel"
      aria-label={`${stats.name}`}
    >
      <header className="tw-panel__head">
        <AgentSprite
          scale={1.7}
          col={col}
          kind={spriteKindOfRank(stats.rank)}
          mood={spriteMoodOfStatus[stats.status]}
        />
        <div>
          <h2 className="tw-panel__name">{stats.name}</h2>
          <p className="tw-card__role">
            {stats.role}
            {stats.district ? ` · ${stats.district}` : ""}
          </p>
          <div
            className="tw-panel__swatch"
            style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}
          >
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: "50%",
                backgroundColor: col,
              }}
            />
            <span style={{ fontSize: 13, opacity: 0.85 }}>
              {colName} · on the map, in chat and on cards
            </span>
          </div>
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
          <ul className="tw-pair-chat">
            {mine.map((m) => {
              const speaker = facts.stats.get(m.from);
              const speakerCol = agentColorByOrder(speaker?.order ?? 0);
              return (
                <li key={m.seq} style={{ borderColor: speakerCol }}>
                  <strong>{name(m.from)}</strong>
                  <time>{clock(first, m.ts)}</time>
                  <p>{agentMessageText(m.text)}</p>
                </li>
              );
            })}
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
