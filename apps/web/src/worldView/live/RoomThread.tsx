// TILO-T-WORLD: the conversation itself, shared by "Talk to <agent>" and the team meeting: the room's turns as bubbles
// (the person's question, the agent's reply with the units it cites), a composer, the room's credits and turns, and
// the change flow: an agent may PROPOSE a change in a reply; only then can the person confirm it (MR-07), and the
// outcome is shown as the API gave it (accepted / queued / failed), never assumed. Nothing here authorises a side
// effect (MR-11): a room turn is a read and a recorded note.
import type { Event } from "@tilo/contracts";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Buddy, Icon } from "../../design/tilo-t";
import type { RoomClient } from "../../park/api/live/meetingHall";
import type { Seat } from "../../park/api/live/roomTalk";
import type { AgentStats } from "../../world/agentStats";
import { roleOf } from "./agentLook";
import { useRoomTalk } from "./useRoomTalk";
import "./live.css";

const OUTCOME_WORD = {
  answered: "Answered from its record",
  proposed_change: "Proposes a change",
  declined: "No record to answer from",
  failed: "Could not answer",
} as const;

const CLOSED = {
  person: "Closed by you",
  idle: "Closed after a quiet spell",
  capped: "The room's credits are used up",
  paused: "Closed because the world was paused",
  access_lost: "Your access changed",
  failed: "Closed after an error",
} as const;

export const CHANGE_STARTER = "I'd like you to take a different direction: ";

export function RoomThread({
  client,
  worldId,
  seat,
  events,
  stats,
  heading,
  defaultTo,
  changeAsk = false,
  autoConvene = false,
}: {
  client: RoomClient | null;
  worldId: string;
  seat: Seat | null;
  events: readonly Event[];
  /** Everyone in the room (the lead first), for names and avatars. */
  stats: readonly AgentStats[];
  heading: string;
  /** Who is asked unless the person picks someone else (the agent whose panel is open). */
  defaultTo?: string;
  /** Offer "Ask them to change direction" (a team meeting); a 1:1 can also use it. */
  changeAsk?: boolean;
  /** Convene the room as soon as this opens (a team meeting: triggeredBy the person pressing Convene team). */
  autoConvene?: boolean;
}) {
  const talk = useRoomTalk(client, worldId, seat, events);
  const { convene } = talk;
  // biome-ignore lint/correctness/useExhaustiveDependencies: convene once, when the meeting opens.
  useEffect(() => {
    if (autoConvene && client && seat) void convene();
  }, []);
  const [to, setTo] = useState(defaultTo ?? stats[stats.length - 1]?.id ?? "");
  const [mode, setMode] = useState<"quick" | "thinking">("quick");
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const who = (id: string) => stats.find((s) => s.id === id);
  const { room } = talk;
  const open = !room || room.state === "open";
  const turns = room?.turns ?? [];
  const waiting = turns.some((t) => !t.reply);
  const proposed = turns.find(
    (t) => t.reply?.proposal && !t.change && !talk.confirmed[t.reply.proposal.proposal_id],
  );
  const proposal = proposed?.reply?.proposal;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || !seat || !to) return;
    void talk.send(to, mode, q).then((ok) => ok && setText(""));
  };

  if (!client || !seat) {
    return (
      <p className="tw-room__off">
        Talking to agents needs the live Tilo service, which this view is not connected to. Nothing
        was asked.
      </p>
    );
  }
  return (
    <section className="tw-room" aria-label={heading}>
      <h3 className="tw-room__h">{heading}</h3>
      {room ? (
        <p className="tw-room__meta">
          {open
            ? `${turns.length} of ${room.max_turns} questions · ${room.credits_spent} of ${room.credit_cap} credits`
            : `Ended · ${room.reason ? CLOSED[room.reason] : "closed"}`}
        </p>
      ) : (
        <p className="tw-room__meta">
          Nothing is asked until you send. Answers come only from this world's record.
        </p>
      )}
      <ol className="tw-room__log" aria-label="Conversation" aria-live="polite">
        {turns.map((t) => {
          const agent = who(t.to);
          return (
            <li key={t.turn} className="tw-room__turn">
              <p className="tw-bubble tw-bubble--me tw-pop">
                <span className="tw-bubble__who">You to {agent?.name ?? t.to}</span>
                {t.text ?? "Question unavailable"}
              </p>
              {t.reply ? (
                <div className="tw-bubble tw-pop" data-outcome={t.reply.outcome}>
                  <span className="tw-bubble__av">
                    <Buddy
                      size={34}
                      role={roleOf(agent?.rank ?? "")}
                      mood={t.reply.outcome === "failed" ? "sad" : "talk"}
                    />
                  </span>
                  <span>
                    <span className="tw-bubble__who">
                      {agent?.name ?? t.to} · {OUTCOME_WORD[t.reply.outcome]}
                    </span>
                    {t.reply.text ?? "No reply was produced. Nothing was made up."}
                    {t.reply.units.length > 0 ? (
                      <span className="tw-bubble__cites">Cites {t.reply.units.join(", ")}</span>
                    ) : null}
                  </span>
                </div>
              ) : (
                <p className="tw-bubble__wait">{agent?.name ?? t.to} is answering…</p>
              )}
            </li>
          );
        })}
      </ol>
      {talk.error ? (
        <p className="tw-room__err" role="alert">
          {talk.error}
        </p>
      ) : null}
      {proposal && open ? (
        <form
          className="tw-room__change"
          onSubmit={(e) => {
            e.preventDefault();
            const field = new FormData(e.currentTarget).get("text");
            void talk.confirm(proposal.proposal_id, String(field ?? "").trim() || "Go ahead.");
          }}
        >
          <p>
            <Icon name="check" size={16} /> {who(proposed?.to ?? "")?.name ?? "The agent"} proposes
            a change to {proposal.units.join(", ")}. Nothing changes until you confirm it.
          </p>
          <textarea
            name="text"
            aria-label="Your wording for the change"
            defaultValue="Go ahead with this change."
          />
          <button type="submit" disabled={talk.busy}>
            Confirm this change
          </button>
        </form>
      ) : null}
      {Object.entries(talk.confirmed).map(([id, said]) => (
        <output key={id} className="tw-room__done">
          Change recorded: {said}.
        </output>
      ))}
      {
        <form className="tw-room__form" onSubmit={submit}>
          {stats.length > 1 ? (
            <label>
              <span>Ask</span>
              <select value={to} onChange={(e) => setTo(e.target.value)}>
                {stats.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label>
            <span>Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as "quick" | "thinking")}>
              <option value="quick">Quick</option>
              <option value="thinking">Thinking</option>
            </select>
          </label>
          <textarea
            ref={box}
            value={text}
            maxLength={2000}
            aria-label="Your question"
            placeholder="Ask what it did and why"
            onChange={(e) => setText(e.target.value)}
          />
          <div className="tw-room__btns">
            <button type="submit" disabled={talk.busy || waiting || !text.trim()}>
              {talk.busy ? "Asking…" : "Send"}
            </button>
            {changeAsk ? (
              <button
                type="button"
                className="tw-room__quiet"
                onClick={() => {
                  setMode("thinking");
                  setText((t) => (t.trim() ? t : CHANGE_STARTER));
                  box.current?.focus();
                }}
              >
                Ask them to change direction
              </button>
            ) : null}
            {room ? (
              <button
                type="button"
                className="tw-room__quiet"
                disabled={talk.busy}
                onClick={() => void talk.adjourn()}
              >
                End conversation
              </button>
            ) : null}
          </div>
        </form>
      }
    </section>
  );
}
