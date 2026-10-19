import { type FormEvent, useEffect, useRef, useState } from "react";
import { TiloApiError } from "../../app/apiError";
import { DirectionForm } from "../../shared/DirectionForm";
import {
  type Attendee,
  type Room,
  type RoomClient,
  attendees,
  confirmChange,
  readRoom,
  roomOf,
  roomPath,
} from "../../api/live/meetingHall";
import { roomFault } from "../../api/live/roomTalk";
import "./MeetingHall.css";

const CLOSED = {
  person: "Closed by request",
  idle: "Inactive",
  capped: "Room limit reached",
  paused: "Work paused",
  access_lost: "Access changed",
  failed: "Could not continue",
};
const OUTCOME = {
  answered: "Answered",
  proposed_change: "Change proposed",
  declined: "Declined",
  failed: "Reply failed",
};

const roleLabel = (rank: string): string =>
  rank.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
const creditsLabel = (credits: number): string => String(Math.round(credits * 10) / 10);

export function MeetingHall({
  worldId,
  client,
  onChangeDirection,
}: {
  worldId: string;
  client: RoomClient;
  onChangeDirection?: (instruction: string) => Promise<void>;
}) {
  const [people, setPeople] = useState<Attendee[] | null>(null);
  const [lead, setLead] = useState("");
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [room, setRoom] = useState<Room | null>(null);
  const [confirmed, setConfirmed] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [questionText, setQuestionText] = useState("");
  const [directionOpen, setDirectionOpen] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState("");
  const active = useRef(true);
  const held = useRef(false);

  useEffect(() => {
    active.current = true;
    attendees(client, worldId).then(
      (rows) => {
        if (!active.current) return;
        setPeople(rows);
        const defaultLead =
          rows.find((a) => a.rank === "director" || (a.rank === "lead" && a.district))?.id ?? "";
        setLead(defaultLead);
      },
      (e) => {
        if (active.current) setError(e instanceof Error ? e.message : "Could not load attendees.");
      },
    );
    return () => {
      active.current = false;
    };
  }, [client, worldId]);

  const pickedLead = people?.find((a) => a.id === lead);
  const choices =
    people?.filter(
      (a) =>
        a.id !== lead &&
        (pickedLead?.rank === "director"
          ? a.rank === "lead"
          : ["writer", "specialist", "verifier"].includes(a.rank) &&
            !!pickedLead?.district &&
            a.district === pickedLead.district),
    ) ?? [];

  const path = roomPath(worldId, room?.room_id);
  const open = room?.state === "open";
  const label = (id: string) => roleLabel(people?.find((a) => a.id === id)?.rank ?? "Agent");

  // Honesty HR rules: speaking ring/indicator ONLY while that agent has a recorded message
  const speakingAgents = new Set(
    room?.turns.filter((t) => Boolean(t.reply?.text)).map((t) => t.reply?.from ?? t.to) ?? [],
  );

  const proposedTurn = room?.turns.find(
    (t) => t.reply?.proposal && !t.change && !confirmed[t.reply.proposal.proposal_id],
  );
  const proposal = proposedTurn?.reply?.proposal;

  async function act(action: string, data = new FormData()) {
    if (held.current) return;
    held.current = true;
    setBusy(true);
    setError("");
    try {
      if (
        (action === "Send" || action === "Send question" || action === "Confirm change") &&
        !String(data.get("text") ?? questionText).trim()
      )
        throw new Error("Please enter a question or change wording.");
      let result: Room | null = null;
      if (action === "Convene") {
        const agents = data.getAll("agents").map(String);
        if (agents.length > 7) throw new Error("Invite up to seven agents.");
        result = roomOf(await client.postJson(path, { lead, agents }), worldId);
      } else if (room && (action === "Send" || action === "Send question")) {
        const textVal = String(data.get("text") || questionText);
        setPendingQuestion(textVal);
        await client.postJson(`${path}/turns`, {
          to: data.get("to"),
          mode: data.get("mode"),
          text: textVal,
        });
        setQuestionText("");
        result = await readRoom(client, worldId, room.room_id);
      } else if (proposal && action === "Confirm change") {
        const id = proposal.proposal_id;
        const status = await confirmChange(client, path, id, String(data.get("text")));
        if (active.current) setConfirmed((c) => ({ ...c, [id]: status }));
      } else if (room)
        result =
          action === "Adjourn" || action === "End conversation"
            ? roomOf(await client.postJson(`${path}/adjourn`, {}), worldId)
            : await readRoom(client, worldId, room.room_id);
      if (active.current && result) setRoom(result);
    } catch (e) {
      if (active.current)
        setError(
          e instanceof TiloApiError
            ? roomFault(e)
            : e instanceof Error
              ? e.message
              : "Could not complete the room action.",
        );
    } finally {
      if (active.current) setPendingQuestion("");
      held.current = false;
      if (active.current) setBusy(false);
    }
  }

  const submit = (action: string) => (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    void act(action, new FormData(e.currentTarget));
  };

  const options = (ids: string[]) =>
    ids.map((id) => (
      <option key={id} value={id}>
        {label(id)}
      </option>
    ));

  const leaders =
    people
      ?.filter((a) => a.rank === "director" || (a.rank === "lead" && a.district))
      .map((a) => a.id) ?? [];

  // Seated agents: if room convened, room lead + agents; if not yet convened, lead + selected choices
  const seatedIds = room ? [room.lead, ...room.agents] : [lead, ...selectedAgents].filter(Boolean);

  const allAgentIds = people?.map((p) => p.id) ?? [];
  const displaySeats = room ? seatedIds : allAgentIds.length > 0 ? allAgentIds : seatedIds;

  return (
    <section className="park-meeting-hall" aria-label="Meeting Hall">
      <header className="park-meeting-head">
        <span className="park-meeting-mark" aria-hidden="true">
          M
        </span>
        <div className="park-meeting-head-text">
          <h2>Meeting Hall</h2>
          <p>Bring the right roles together for a focused conversation.</p>
        </div>
        {room ? (
          <div className="park-meeting-head-meta">
            <span className="park-meeting-roommeta">
              {creditsLabel(room.credits_spent)} of {creditsLabel(room.credit_cap)} credits
            </span>
            <span className="park-meeting-status-tag">
              {open
                ? [room.turns.length, " / ", room.max_turns, " turns"].join("")
                : `Adjourned · ${room.reason ? CLOSED[room.reason] : "Reason unavailable"}`}
            </span>
          </div>
        ) : null}
      </header>

      {error ? <p role="alert">{error}</p> : null}
      {!people && !error ? <p>Loading recorded attendees…</p> : null}

      <div className="park-meeting-body" aria-busy={busy}>
        {people && !room && !lead ? <p>No recorded lead is available for this world.</p> : null}

        {people && (room || lead) ? (
          <div className="park-meeting-room-view">
            {/* The Meeting Room Scene with Top-down Table and Seats */}
            <section className="park-meeting-scene" aria-label="Conference Room">
              <div className="park-meeting-room-stage">
                {/* Conference Table */}
                <div className="park-meeting-table" aria-hidden="true">
                  <div className="park-meeting-table-surface">
                    <span className="park-meeting-table-title">Conference Table</span>
                    <span className="park-meeting-table-sub">
                      {room ? (open ? "In Session" : "Adjourned") : "Pre-meeting"}
                    </span>
                  </div>
                </div>

                {/* Seats around the table */}
                <div className="park-meeting-seats">
                  {displaySeats.map((id) => {
                    const isSeated = seatedIds.includes(id);
                    const isLead = room ? room.lead === id : lead === id;
                    const isSpeaking = speakingAgents.has(id);
                    return (
                      <div
                        key={id}
                        className={`park-meeting-seat${isSeated ? " park-meeting-seat--active" : " park-meeting-seat--empty"}${isLead ? " park-meeting-seat--lead" : ""}${isSpeaking ? " park-meeting-seat--speaking" : ""}`}
                      >
                        <div className="park-meeting-seat-avatar-wrap">
                          <span
                            className="park-meeting-avatar park-meeting-seat-avatar"
                            aria-hidden="true"
                          >
                            {label(id).slice(0, 1)}
                          </span>
                          {isSpeaking ? (
                            <span className="park-meeting-speaking-ring" aria-hidden="true" />
                          ) : null}
                        </div>
                        <span className="park-meeting-seat-name">{label(id)}</span>
                        {isSpeaking ? (
                          <span className="park-meeting-speaking-badge">Speaking</span>
                        ) : isLead ? (
                          <span className="park-meeting-lead-badge">Lead</span>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Call to the table tray */}
              {!room && lead ? (
                <form className="park-meeting-setup" onSubmit={submit("Convene")}>
                  <fieldset className="park-meeting-group">
                    <legend className="park-meeting-label">Lead</legend>
                    <div className="park-meeting-pills">
                      {leaders.map((id) => (
                        <button
                          key={id}
                          type="button"
                          className="park-meeting-rolepill"
                          aria-pressed={lead === id}
                          onClick={() => {
                            setLead(id);
                            setSelectedAgents([]);
                          }}
                        >
                          {label(id)}
                        </button>
                      ))}
                    </div>
                  </fieldset>

                  <fieldset key={lead} className="park-meeting-invites park-meeting-tray">
                    <legend className="park-meeting-label">Call to the table</legend>
                    <p className="park-meeting-tray-desc">
                      Click an agent to seat them at the table (up to seven):
                    </p>
                    <div className="park-meeting-tray-grid">
                      {choices.map((a) => {
                        const checked = selectedAgents.includes(a.id);
                        return (
                          <label key={a.id} className="park-meeting-agentchip">
                            <input
                              type="checkbox"
                              name="agents"
                              value={a.id}
                              checked={checked}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  setSelectedAgents((cur) => [...cur, a.id]);
                                } else {
                                  setSelectedAgents((cur) => cur.filter((x) => x !== a.id));
                                }
                              }}
                            />
                            <span className="park-meeting-avatar" aria-hidden="true">
                              {label(a.id).slice(0, 1)}
                            </span>
                            {label(a.id)}
                          </label>
                        );
                      })}
                    </div>
                  </fieldset>

                  <button
                    type="submit"
                    className="park-btn park-btn--primary park-btn--md park-meeting-convene"
                    disabled={busy}
                  >
                    Convene
                  </button>
                </form>
              ) : null}

              {room ? (
                <div className="park-meeting-tray park-meeting-tray--convened">
                  <span className="park-meeting-label">Seated at table</span>
                  <div className="park-meeting-tray-grid">
                    {seatedIds.map((id) => (
                      <div
                        key={id}
                        className="park-meeting-agentchip park-meeting-agentchip--active"
                      >
                        <span className="park-meeting-avatar" aria-hidden="true">
                          {label(id).slice(0, 1)}
                        </span>
                        {label(id)}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>

            {/* Transcript as Chat Bubbles Beside the Room */}
            {room ? (
              <section className="park-meeting-transcript-pane" aria-label="Meeting Transcript">
                <div className="park-meeting-transcript-head">
                  <h3>Transcript</h3>
                  <button
                    type="button"
                    className="park-btn park-btn--secondary park-btn--sm"
                    onClick={() => void act("Refresh replies")}
                    disabled={busy}
                  >
                    Refresh replies
                  </button>
                </div>

                <div className="park-meeting-chat-bubbles" role="log" aria-live="polite">
                  {room.turns.length === 0 && !pendingQuestion ? (
                    <p className="park-meeting-empty-chat">
                      No turns yet. Send a question below to start the meeting discussion.
                    </p>
                  ) : (
                    room.turns.map((t) => (
                      <div key={t.turn} className="park-meeting-turn">
                        {/* User question bubble */}
                        <div className="park-meeting-bubble park-meeting-bubble--user">
                          <div className="park-meeting-bubble-meta">
                            <span className="park-meeting-bubble-sender">You</span>
                            <span className="park-meeting-bubble-target">
                              to {label(t.to)} · Turn {t.turn} · {t.mode}
                            </span>
                          </div>
                          <div className="park-meeting-bubble-text">
                            {t.text ?? "Question unavailable"}
                          </div>
                        </div>

                        {/* Agent reply bubble */}
                        <div className="park-meeting-bubble park-meeting-bubble--agent">
                          <div className="park-meeting-bubble-meta">
                            <span
                              className="park-meeting-avatar park-meeting-bubble-avatar"
                              aria-hidden="true"
                            >
                              {label(t.reply?.from ?? t.to).slice(0, 1)}
                            </span>
                            <span className="park-meeting-bubble-sender">
                              {label(t.reply?.from ?? t.to)}
                            </span>
                            {t.reply ? (
                              <span className="park-meeting-bubble-outcome">
                                {[
                                  OUTCOME[t.reply.outcome],
                                  t.reply.units.length,
                                  "cited units",
                                ].join(" · ")}
                              </span>
                            ) : null}
                          </div>
                          <div className="park-meeting-bubble-text">
                            {t.reply
                              ? (t.reply.text ?? "No reply was produced.")
                              : "Reply pending. Refresh to check."}
                          </div>
                          {t.reply?.proposal &&
                          !t.change &&
                          !confirmed[t.reply.proposal.proposal_id] ? (
                            <div className="park-meeting-proposal-notice">
                              Proposal pending · Turn {t.turn}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))
                  )}
                  {pendingQuestion ? (
                    <div className="park-meeting-turn">
                      <div className="park-meeting-bubble park-meeting-bubble--user">
                        <span className="park-meeting-bubble-sender">You</span>
                        <div className="park-meeting-bubble-text">{pendingQuestion}</div>
                      </div>
                      <output
                        className="park-meeting-bubble park-meeting-bubble--agent"
                        aria-label="Agent typing"
                      >
                        Agent is answering…
                      </output>
                    </div>
                  ) : null}
                </div>

                {Object.entries(confirmed).map(([id, status]) => (
                  <output key={id} className="park-meeting-confirmed">
                    {status}
                  </output>
                ))}

                {proposal && open ? (
                  <form
                    key={proposal.proposal_id}
                    className="park-meeting-form park-meeting-proposal-form"
                    onSubmit={submit("Confirm change")}
                  >
                    <fieldset disabled={busy}>
                      <legend className="park-meeting-proposal-title">
                        Change from turn {proposedTurn?.turn} ·{" "}
                        {label(proposedTurn?.to ?? room.lead)}
                      </legend>
                      <p className="park-meeting-proposal-units">
                        Units: {proposal.units.join(", ")}
                      </p>
                      <label>
                        Change wording
                        <textarea name="text" required maxLength={2000} />
                      </label>
                      <button type="submit" className="park-btn park-btn--secondary park-btn--md">
                        Confirm change
                      </button>
                    </fieldset>
                  </form>
                ) : null}
              </section>
            ) : null}

            {/* Message Box Below with Send, End conversation, Ask them to change direction */}
            {room && open ? (
              <form className="park-meeting-composer" onSubmit={submit("Send")}>
                <fieldset
                  disabled={
                    busy || room.turns.some((t) => !t.reply) || room.turns.length >= room.max_turns
                  }
                >
                  <div className="park-meeting-composer-fields">
                    <label className="park-meeting-composer-select">
                      Ask
                      <select name="to">{options([room.lead, ...room.agents])}</select>
                    </label>
                    <label className="park-meeting-composer-select">
                      Mode
                      <select name="mode">
                        <option value="quick">Quick</option>
                        <option value="thinking">Thinking</option>
                      </select>
                    </label>
                  </div>

                  <label className="park-meeting-composer-textarea">
                    Question
                    <textarea
                      name="text"
                      value={questionText}
                      onChange={(e) => setQuestionText(e.target.value)}
                      placeholder="Ask the table a question or give direction..."
                      required
                      maxLength={2000}
                    />
                  </label>

                  <div className="park-meeting-composer-actions">
                    <button type="submit" className="park-btn park-btn--primary park-btn--md">
                      Send
                    </button>
                    <button
                      type="button"
                      className="park-btn park-btn--secondary park-btn--md"
                      onClick={() => void act("Adjourn")}
                    >
                      End conversation
                    </button>
                    {onChangeDirection ? (
                      <button
                        type="button"
                        className="park-btn park-btn--secondary park-btn--md"
                        aria-expanded={directionOpen}
                        onClick={() => setDirectionOpen((open) => !open)}
                      >
                        Ask them to change direction
                      </button>
                    ) : null}
                  </div>
                </fieldset>
              </form>
            ) : null}
            {directionOpen && onChangeDirection ? (
              <DirectionForm onStart={onChangeDirection} onCancel={() => setDirectionOpen(false)} />
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
