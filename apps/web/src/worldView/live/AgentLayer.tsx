// TILO-T-WORLD: everything laid over the live stage that is about the agents: the hover stats card now, the agent
// panel ("Talk to") and the team meeting next. It reads the same replayed events as the Story (useWorldFacts), and the
// stage's spotlight (display state), and writes nothing of its own.
import { useMemo, useState } from "react";
import { Icon } from "../../design/tilo-t";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { agentRoleColor } from "../../world/agentRole";
import type { Message } from "../../world/conversations";
import { openAgent, registerProbe, useSpotlight } from "../../world/spotlight";
import { useWorldFacts } from "../../world/useWorldFacts";
import { AgentCard } from "./AgentCard";
import { AgentPanel } from "./AgentPanel";
import { ChatPopUp } from "./ChatPopUp";
import { PlaybackBar } from "./PlaybackBar";
import { StageEvents } from "./StageEvents";
import { TeamMeeting } from "./TeamMeeting";

export function AgentLayer({ worldId, rooms }: { worldId: string; rooms: RoomClient | null }) {
  const facts = useWorldFacts(worldId, rooms);
  const [team, setTeam] = useState(false);
  const [chat, setChat] = useState<{ open: boolean; filter: string } | null>(null);
  const spot = useSpotlight(worldId);
  const hovered = spot.hover && spot.opened !== spot.hover ? facts.stats.get(spot.hover) : null;
  const opened = spot.opened ? facts.stats.get(spot.opened) : null;
  const talking = useMemo(() => {
    const handoff = [...facts.messages].reverse().find((m) => {
      const from = facts.stats.get(m.from);
      const to = facts.stats.get(m.to);
      const validKind = m.kind === "handoff" || m.kind === "question";
      return validKind && from?.status === "handing over" && !!to;
    });
    if (!handoff) return null;
    const probe = registerProbe.get(worldId);
    if (probe?.isWalking?.(handoff.from) || probe?.isWalking?.(handoff.to)) {
      return null;
    }
    const a = probe?.locate(handoff.from);
    const b = probe?.locate(handoff.to);
    return a && b
      ? { message: handoff, at: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 - 34 } }
      : null;
  }, [facts.messages, facts.stats, worldId]);
  return (
    <>
      <PlaybackBar worldId={worldId} />
      <StageEvents worldId={worldId} layout={facts.layout} events={facts.events} />
      {talking && !team ? (
        <button
          type="button"
          className="tw-talk-dots tw-talking-dots"
          style={{ left: talking.at.x, top: talking.at.y }}
          aria-label={`Open conversation between ${facts.names.get(talking.message.from) ?? "agents"} and ${facts.names.get(talking.message.to) ?? "agents"}`}
          data-testid="world-talk-dots"
          onClick={() => {
            const pair = [talking.message.from, talking.message.to].sort().join(",");
            setChat({ open: true, filter: `pair:${pair}` });
          }}
        >
          <span />
          <span />
          <span />
        </button>
      ) : null}
      {chat?.open ? (
        <ChatPopUp
          worldId={worldId}
          facts={facts}
          events={facts.events}
          rooms={rooms}
          initialFilter={chat.filter}
          onClose={() => setChat(null)}
          onConvene={() => {
            setChat(null);
            setTeam(true);
          }}
        />
      ) : null}
      {facts.layout && !team && !opened ? (
        <button type="button" className="tw-convene" onClick={() => setTeam(true)}>
          <Icon name="people" size={18} /> Convene team
        </button>
      ) : null}
      {team ? (
        <TeamMeeting
          worldId={worldId}
          facts={facts}
          events={facts.events}
          rooms={rooms}
          onClose={() => setTeam(false)}
          onConvene={() => {
            setChat({ open: true, filter: "meeting" });
          }}
        />
      ) : null}
      {hovered && spot.point ? <AgentCard stats={hovered} at={spot.point} /> : null}
      {opened && !team ? (
        <AgentPanel
          key={opened.id}
          worldId={worldId}
          stats={opened}
          facts={facts}
          events={facts.events}
          rooms={rooms}
          onClose={() => openAgent(worldId, null)}
        />
      ) : null}
    </>
  );
}
