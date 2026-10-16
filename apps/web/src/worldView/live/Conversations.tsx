// TILO-T-WORLD: the world's chat: how the agents talk to each other, as a thread, live as events arrive. Every line is
// one recorded message (a Lead giving a unit, a handoff note, a question and its answer, a reviewer's verdict, a room
// turn) with its real words, read from the same event slice and archive as the Story (HR-1, MR-12). Nothing is
// summarised away and nothing is written here. Clicking a line flies the camera to where it happened and lights both
// agents on the stage (display state only).
import { useEffect, useMemo, useRef, useState } from "react";
import { Buddy, EmptyState, Icon } from "../../design/tilo-t";
import type { RoomClient } from "../../park/api/live/meetingHall";
import {
  type Message,
  type MessageKind,
  filterMessages,
  partiesOf,
} from "../../world/conversations";
import { select } from "../../world/selection";
import { flyTo, setLit } from "../../world/spotlight";
import { useWorldFacts } from "../../world/useWorldFacts";
import { MOOD_OF_STATUS, clock, roleOf } from "./agentLook";
import "./live.css";

export const KIND_WORD: Readonly<Record<MessageKind, string>> = {
  assigned: "gave a task",
  handoff: "handed over",
  help: "asked for help",
  question: "asked a question",
  answer: "answered",
  review: "reviewed",
  convened: "called a meeting",
  asked: "asked in the room",
  replied: "replied in the room",
  change: "asked for a change",
  adjourned: "ended the meeting",
};

const NO_WORDS =
  "The words of this turn are kept in the room archive and are not available to show.";

export function Conversations({ worldId, rooms }: { worldId: string; rooms: RoomClient | null }) {
  const facts = useWorldFacts(worldId, rooms);
  const [agent, setAgent] = useState("");
  const [other, setOther] = useState("");
  const parties = useMemo(() => partiesOf(facts.messages), [facts.messages]);
  const shown = useMemo(
    () => filterMessages(facts.messages, { agent, other }),
    [facts.messages, agent, other],
  );
  const name = (id: string) =>
    facts.names.get(id) ?? (id.startsWith("u_") || id === "system" ? "You" : id);
  const rank = (id: string) => facts.layout?.semantic.agents.find((a) => a.id === id)?.rank ?? "";
  const first = facts.events[0]?.ts;

  const log = useRef<HTMLOListElement>(null);
  const stick = useRef(true);
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new message is the trigger to follow the thread's end.
  useEffect(() => {
    const el = log.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [shown.length]);

  const open = (m: Message) => {
    // triggeredBy: the person's click on a recorded message (display only): fly there, light both speakers.
    const ids = [m.from, m.to].filter((id) => facts.names.has(id));
    setLit(worldId, ids);
    const target = m.where ?? ids[0];
    if (target) flyTo(worldId, target, 900);
    if (ids[0]) select(worldId, ids[0]);
  };

  if (!facts.layout) return <p className="tw-chat__note">Loading the team…</p>;
  const counterparts = agent ? (parties.get(agent) ?? []) : [];
  return (
    <section className="tw-chat" aria-label="Conversations">
      <div className="tw-chat__filters">
        <label>
          <span>Agent</span>
          <select
            value={agent}
            onChange={(e) => {
              setAgent(e.target.value);
              setOther("");
            }}
          >
            <option value="">Everyone</option>
            {[...parties.keys()].map((id) => (
              <option key={id} value={id}>
                {name(id)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>With</span>
          <select value={other} onChange={(e) => setOther(e.target.value)} disabled={!agent}>
            <option value="">Anyone</option>
            {counterparts.map((id) => (
              <option key={id} value={id}>
                {name(id)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {shown.length === 0 ? (
        <EmptyState
          title="No conversations yet"
          body="When agents hand work to each other or ask a question, the words appear here as they happen."
        />
      ) : (
        <ol
          ref={log}
          className="tw-chat__log"
          aria-label="Messages between agents, oldest first"
          aria-live="polite"
          onScroll={(e) => {
            const el = e.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
          }}
        >
          {shown.map((m) => {
            const person = !facts.names.has(m.from);
            return (
              <li
                key={m.seq}
                className="tw-msg tw-pop"
                data-seq={m.seq}
                data-kind={m.kind}
                data-person={person}
              >
                <button type="button" className="tw-msg__btn" onClick={() => open(m)}>
                  <span className="tw-msg__who">
                    {person ? (
                      <Icon name="people" size={22} />
                    ) : (
                      <Buddy
                        size={34}
                        role={roleOf(rank(m.from))}
                        mood={MOOD_OF_STATUS[facts.stats.get(m.from)?.status ?? "ready"]}
                      />
                    )}
                  </span>
                  <span className="tw-msg__body">
                    <span className="tw-msg__meta">
                      <strong>{name(m.from)}</strong>
                      <span aria-hidden="true">→</span>
                      <span>{name(m.to)}</span>
                      <span className="tw-msg__kind">{KIND_WORD[m.kind]}</span>
                      <time>{clock(first, m.ts)}</time>
                    </span>
                    <span className="tw-msg__text">{m.text ?? NO_WORDS}</span>
                    {m.detail.length > 0 ? (
                      <ul className="tw-msg__detail" aria-label="Acceptance criteria">
                        {m.detail.map((d) => (
                          <li key={d}>{d}</li>
                        ))}
                      </ul>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
