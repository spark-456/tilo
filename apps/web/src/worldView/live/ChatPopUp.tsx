// TW-4: WhatsApp-like chat pop-up (open 220 ms / close 160 ms) from an agent, a pair, or the 3 dots.
// Plain-sentence messages with avatars, times, hand-over note cards with file names.
// Filters: All / pair / agent / You / Team meeting; Convene dialog opens from header.
import type { Event } from "@tilo/contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "../../design/tilo-t";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { seatFor } from "../../park/api/live/roomTalk";
import type { Message } from "../../world/conversations";
import type { WorldFacts } from "../../world/useWorldFacts";
import { clock } from "./agentLook";
import { agentMessageText } from "./agentMessageText";
import { useRoomTalk } from "./useRoomTalk";
import "./ChatPopUp.css";
import "./live.css";

const AGENT_COLORS = ["ag1", "ag2", "ag3", "ag4", "ag5", "ag6", "ag7"] as const;

export function agentColorKey(id: string, allIds: readonly string[] = []): string {
  const idx = allIds.indexOf(id);
  if (idx >= 0) return AGENT_COLORS[idx % AGENT_COLORS.length] ?? "ag1";
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return AGENT_COLORS[h % AGENT_COLORS.length] ?? "ag1";
}

interface ChatPopUpProps {
  worldId: string;
  facts: WorldFacts;
  events: readonly Event[];
  rooms: RoomClient | null;
  initialFilter?: string;
  onClose: () => void;
  onConvene: () => void;
}

export function ChatPopUp({
  worldId,
  facts,
  events,
  rooms,
  initialFilter = "all",
  onClose,
  onConvene,
}: ChatPopUpProps) {
  const [filter, setFilter] = useState(initialFilter);
  const [closing, setClosing] = useState(false);
  const [inputVal, setInputVal] = useState("");
  const [pending, setPending] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  const agentIds = useMemo(
    () => (facts.layout?.semantic.agents ?? []).map((a) => a.id),
    [facts.layout],
  );
  const talkTarget = useMemo(() => {
    if (filter.startsWith("agent:")) return filter.slice(6);
    if (filter.startsWith("pair:")) return filter.slice(5).split(",")[1] ?? "";
    const agents = facts.layout?.semantic.agents ?? [];
    return (
      agents.find((agent) => agent.rank === "director")?.id ??
      agents.find((agent) => agent.rank === "lead")?.id ??
      ""
    );
  }, [facts.layout, filter]);
  const talkSeat = useMemo(
    () => (facts.layout && talkTarget ? seatFor(facts.layout, events, talkTarget) : null),
    [events, facts.layout, talkTarget],
  );
  const talk = useRoomTalk(rooms, worldId, talkSeat, events);

  const handleClose = () => {
    if (closing) return;
    setClosing(true);
    setTimeout(onClose, 160);
  };

  const nameOf = useCallback(
    (id: string) => {
      if (id === "me" || id.startsWith("u_") || id === "system") return "You";
      if (id === "meeting" || id === "team") return "Team meeting";
      return facts.names.get(id) ?? id;
    },
    [facts.names],
  );

  const roleOf = useCallback(
    (id: string) => {
      const sem = facts.layout?.semantic.agents.find((a) => a.id === id);
      return sem?.rank ? sem.rank.charAt(0).toUpperCase() + sem.rank.slice(1) : "Specialist";
    },
    [facts.layout],
  );

  // Determine available filters: All, pairs, agents, You, Team meeting
  const filterList = useMemo(() => {
    const list: Array<{ key: string; label: string; dots: string[] }> = [
      { key: "all", label: "All", dots: [] },
    ];
    // Check if meetings exist
    const hasMeeting =
      facts.events.some((e) => e.type.startsWith("meeting.")) ||
      facts.messages.some((m) => m.kind === "convened" || m.to === "meeting");
    if (hasMeeting) {
      list.push({ key: "meeting", label: "Team meeting", dots: [] });
    }
    // Pairs from message history
    const pairsSeen = new Set<string>();
    for (const m of facts.messages) {
      if (m.from && m.to && m.from !== m.to && !m.from.startsWith("u_") && !m.to.startsWith("u_")) {
        const pairKey = [m.from, m.to].sort().join(",");
        if (!pairsSeen.has(pairKey)) {
          pairsSeen.add(pairKey);
          const [a, b] = pairKey.split(",") as [string, string];
          list.push({
            key: `pair:${pairKey}`,
            label: `${nameOf(a)} & ${nameOf(b)}`,
            dots: [agentColorKey(a, agentIds), agentColorKey(b, agentIds)],
          });
        }
      }
    }
    // Single agents
    for (const ag of agentIds) {
      list.push({
        key: `agent:${ag}`,
        label: nameOf(ag),
        dots: [agentColorKey(ag, agentIds)],
      });
    }
    list.push({ key: "me", label: "You", dots: [] });
    return list;
  }, [facts.messages, facts.events, agentIds, nameOf]);

  // Messages filtered according to active filter
  const shownMessages = useMemo(() => {
    return facts.messages.filter((m) => {
      if (filter === "meeting") {
        return (
          m.kind === "convened" ||
          m.kind === "asked" ||
          m.kind === "replied" ||
          m.kind === "change" ||
          m.kind === "adjourned" ||
          m.to === "meeting"
        );
      }
      if (filter === "me") {
        return (
          m.from === "me" ||
          m.to === "me" ||
          m.from.startsWith("u_") ||
          m.to.startsWith("u_") ||
          m.to === "meeting"
        );
      }
      if (filter.startsWith("pair:")) {
        const [a, b] = filter.slice(5).split(",") as [string, string];
        return (m.from === a && m.to === b) || (m.from === b && m.to === a);
      }
      if (filter.startsWith("agent:")) {
        const ag = filter.slice(6);
        return m.from === ag || m.to === ag;
      }
      return true;
    });
  }, [facts.messages, filter]);

  // Header avatars, title and subtitle
  const headerMeta = useMemo(() => {
    if (filter === "meeting") {
      const attendees = agentIds.slice(0, 3);
      return {
        title: "Team meeting",
        sub: `In the Meeting Hall · ${Math.max(agentIds.length, 3)} agents listening`,
        avatars: attendees.map((id) => ({ id, col: agentColorKey(id, agentIds) })),
        toName: "the meeting",
      };
    }
    if (filter.startsWith("pair:")) {
      const [a, b] = filter.slice(5).split(",") as [string, string];
      return {
        title: `${nameOf(a)} & ${nameOf(b)}`,
        sub: "Their conversation",
        avatars: [
          { id: a, col: agentColorKey(a, agentIds) },
          { id: b, col: agentColorKey(b, agentIds) },
        ],
        toName: nameOf(b),
      };
    }
    if (filter.startsWith("agent:")) {
      const ag = filter.slice(6);
      return {
        title: nameOf(ag),
        sub: `${roleOf(ag)} · everything to and from ${nameOf(ag)}`,
        avatars: [{ id: ag, col: agentColorKey(ag, agentIds) }],
        toName: nameOf(ag),
      };
    }
    if (filter === "me") {
      return {
        title: "Your messages",
        sub: "Your 1:1s and meetings",
        avatars: agentIds.slice(0, 3).map((id) => ({ id, col: agentColorKey(id, agentIds) })),
        toName: agentIds[0] ? nameOf(agentIds[0]) : "Team",
      };
    }
    return {
      title: "Team chat",
      sub: "What the agents said, in plain words",
      avatars: agentIds.slice(0, 3).map((id) => ({ id, col: agentColorKey(id, agentIds) })),
      toName: agentIds[0] ? nameOf(agentIds[0]) : "Kai",
    };
  }, [filter, agentIds, nameOf, roleOf]);

  const firstTs = events[0]?.ts;

  // Autoscroll
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll down on message change
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [shownMessages.length, talk.room?.turns.length, pending, filter]);

  const handleSend = () => {
    const text = inputVal.trim();
    if (!text || !rooms || !talkSeat || !talkTarget || talk.busy) return;
    setPending(text);
    setInputVal("");
    void talk.send(talkTarget, "quick", text).finally(() => setPending(""));
  };

  return (
    <aside
      className={
        closing ? "tw-chat-popup tw-chat-popup--closing" : "tw-chat-popup tw-chat-popup--open"
      }
      data-testid="world-talk-chat"
      aria-label="Agent conversation"
    >
      <header className="tw-chat-popup__head">
        <div className="tw-chat-av-stack">
          {headerMeta.avatars.map((av) => (
            <span key={av.id} className="tw-chat-av" data-ag-color={av.col} aria-hidden="true">
              <span className="tw-chat-visor">
                <span className="tw-chat-eye" />
                <span className="tw-chat-eye" />
              </span>
            </span>
          ))}
        </div>
        <div className="tw-chat-popup__meta">
          <strong className="tw-chat-popup__title">{headerMeta.title}</strong>
          <span className="tw-chat-popup__sub">{headerMeta.sub}</span>
        </div>
        <button
          type="button"
          className="tw-chat-popup__convene"
          onClick={onConvene}
          aria-label="Convene team"
        >
          <Icon name="people" size={16} />
          <span>Convene</span>
        </button>
        <button
          type="button"
          className="tw-chat-popup__close"
          aria-label="Close chat"
          onClick={handleClose}
        >
          ×
        </button>
      </header>

      <div role="tablist" aria-label="Filter conversations" className="tw-chat-filterbar">
        {filterList.map((f) => {
          const active = filter === f.key;
          return (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={active}
              className={active ? "tw-chat-filter tw-chat-filter--active" : "tw-chat-filter"}
              onClick={() => setFilter(f.key)}
            >
              {f.dots.map((d) => (
                <span key={`${f.key}-${d}`} className="tw-chat-filter__dot" data-ag-color={d} />
              ))}
              <span>{f.label}</span>
            </button>
          );
        })}
      </div>

      <div ref={logRef} className="tw-chat-thread" aria-live="polite">
        <span className="tw-chat-today">Today</span>

        {shownMessages.length === 0 && !talk.room?.turns.length && !pending ? (
          <p className="tw-chat-empty">No messages in this view yet.</p>
        ) : null}

        {shownMessages.map((m, idx) => {
          const isMe = m.from === "me" || m.from.startsWith("u_") || m.from === "system";
          const isSys = m.kind === "convened" || m.to === "meeting";
          const prev = shownMessages[idx - 1];
          const firstInGroup = !prev || prev.from !== m.from;
          const time = clock(firstTs, m.ts);
          const colKey = agentColorKey(m.from, agentIds);
          const toL =
            m.to === "meeting"
              ? ""
              : m.to.startsWith("u_") || m.to === "me"
                ? "to you"
                : `to ${nameOf(m.to)}`;

          if (isSys && m.kind === "convened") {
            return (
              <div key={m.seq} className="tw-chat-sys">
                <Icon name="people" size={14} />
                <span>
                  Team meeting · {agentIds.slice(0, 3).map(nameOf).join(", ")} · {time}
                </span>
              </div>
            );
          }

          if (isMe) {
            return (
              <div key={m.seq} className="tw-chat-row tw-chat-row--me">
                {firstInGroup ? (
                  <span className="tw-chat-sender">
                    <strong>You</strong>
                    {toL ? <span className="tw-chat-to">{toL}</span> : null}
                  </span>
                ) : null}
                <div className="tw-chat-bubble tw-chat-bubble--me">
                  <span className="tw-chat-text">{agentMessageText(m.text)}</span>
                  <time className="tw-chat-time">{time} · seen</time>
                </div>
              </div>
            );
          }

          const isHandoff = m.kind === "handoff" || m.detail.length > 0;
          const isAsk = m.kind === "question";
          const fileName = m.detail[0] ?? "handoff-notes.md";

          return (
            <div key={m.seq} className="tw-chat-row tw-chat-row--agent">
              <span
                className={`tw-chat-av $firstInGroup ? "" : "tw-chat-av--ghost"`}
                data-ag-color={colKey}
                aria-hidden="true"
              >
                <span className="tw-chat-visor">
                  <span className="tw-chat-eye" />
                  <span className="tw-chat-eye" />
                </span>
              </span>
              <div className="tw-chat-bubble-wrap">
                {firstInGroup ? (
                  <span className="tw-chat-sender">
                    <strong>{nameOf(m.from)}</strong>
                    {toL ? <span className="tw-chat-to">{toL}</span> : null}
                  </span>
                ) : null}
                <div
                  className={isAsk ? "tw-chat-bubble tw-chat-bubble--ask" : "tw-chat-bubble"}
                  data-ag-tint={colKey}
                >
                  {isHandoff ? (
                    <div className="tw-chat-handover">
                      <span className="tw-chat-handover__tag">
                        HAND-OVER · {nameOf(m.to).toUpperCase()}
                      </span>
                      <p className="tw-chat-handover__note">{agentMessageText(m.text)}</p>
                      <span className="tw-chat-handover__file">
                        <Icon name="file" size={14} />
                        <span>{fileName}</span>
                      </span>
                    </div>
                  ) : isAsk ? (
                    <div className="tw-chat-ask">
                      <span className="tw-chat-ask__tag">NEEDS YOUR YES</span>
                      <p className="tw-chat-ask__text">{agentMessageText(m.text)}</p>
                    </div>
                  ) : (
                    <span className="tw-chat-text">{agentMessageText(m.text)}</span>
                  )}
                  <time className="tw-chat-time">{time}</time>
                </div>
              </div>
            </div>
          );
        })}

        {talk.room?.turns.map((turn) => (
          <div key={`room-${turn.turn}`} className="tw-chat-room-turn">
            <div className="tw-chat-row tw-chat-row--me">
              <span className="tw-chat-sender">
                <strong>You</strong> <span className="tw-chat-to">to {nameOf(turn.to)}</span>
              </span>
              <div className="tw-chat-bubble tw-chat-bubble--me">
                <span className="tw-chat-text">{turn.text ?? "Question unavailable"}</span>
              </div>
            </div>
            {turn.reply ? (
              <div className="tw-chat-row tw-chat-row--agent">
                <div className="tw-chat-bubble" data-outcome={turn.reply.outcome}>
                  <span className="tw-chat-sender">
                    <strong>{nameOf(turn.reply.from)}</strong>
                  </span>
                  <span className="tw-chat-text">
                    {turn.reply.text ?? "No reply was produced. Nothing was made up."}
                  </span>
                  {turn.reply.artifacts.length > 0 ? (
                    <span className="tw-chat-to">
                      Artifacts {turn.reply.artifacts.map((item) => item.artifact_id).join(", ")}
                    </span>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        ))}

        {pending ? (
          <>
            <div className="tw-chat-row tw-chat-row--me">
              <span className="tw-chat-sender">
                <strong>You</strong> <span className="tw-chat-to">to {headerMeta.toName}</span>
              </span>
              <div className="tw-chat-bubble tw-chat-bubble--me tw-chat-bubble--pending">
                <span className="tw-chat-text">{pending}</span>
              </div>
            </div>
            <output className="tw-chat-typing">
              <span aria-hidden="true">•••</span> {nameOf(talkTarget)} is answering…
            </output>
          </>
        ) : null}
        {talk.error ? (
          <p className="tw-room__err" role="alert">
            {talk.error}
          </p>
        ) : null}
      </div>

      <div className="tw-chat-bottom">
        <span className="tw-chat-to-badge">To {headerMeta.toName}</span>
        <input
          type="text"
          className="tw-chat-input"
          placeholder={`Message ${headerMeta.toName}…`}
          value={inputVal}
          disabled={!rooms || !talkSeat || talk.busy}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        <button
          type="button"
          className="tw-chat-send"
          aria-label="Send"
          disabled={!inputVal.trim() || !rooms || !talkSeat || talk.busy}
          onClick={handleSend}
        >
          <Icon name="send" size={16} />
        </button>
      </div>
    </aside>
  );
}
