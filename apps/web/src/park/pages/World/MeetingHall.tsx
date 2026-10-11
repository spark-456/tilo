import { type FormEvent, type ReactNode, useEffect, useRef, useState } from "react";
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

export function MeetingHall({ worldId, client }: { worldId: string; client: RoomClient }) {
  const [people, setPeople] = useState<Attendee[] | null>(null);
  const [lead, setLead] = useState("");
  const [room, setRoom] = useState<Room | null>(null);
  const [confirmed, setConfirmed] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  const held = useRef(false);
  useEffect(() => {
    active.current = true;
    attendees(client, worldId).then(
      (rows) => {
        if (!active.current) return;
        setPeople(rows);
        setLead(
          rows.find((a) => a.rank === "director" || (a.rank === "lead" && a.district))?.id ?? "",
        );
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
  const label = (id: string) => [people?.find((a) => a.id === id)?.rank ?? "Agent", id].join(" · ");
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
        (action === "Send question" || action === "Confirm change") &&
        !String(data.get("text") ?? "").trim()
      )
        throw new Error("Please enter a question or change wording.");
      let result: Room | null = null;
      if (action === "Convene") {
        const agents = data.getAll("agents").map(String);
        if (agents.length > 7) throw new Error("Invite up to seven agents.");
        result = roomOf(await client.postJson(path, { lead, agents }), worldId);
      } else if (room && action === "Send question") {
        await client.postJson(`${path}/turns`, {
          to: data.get("to"),
          mode: data.get("mode"),
          text: data.get("text"),
        });
        result = await readRoom(client, worldId, room.room_id);
      } else if (proposal && action === "Confirm change") {
        const id = proposal.proposal_id;
        const status = await confirmChange(client, path, id, String(data.get("text")));
        if (active.current) setConfirmed((c) => ({ ...c, [id]: status }));
      } else if (room)
        result =
          action === "Adjourn"
            ? roomOf(await client.postJson(`${path}/adjourn`, {}), worldId)
            : await readRoom(client, worldId, room.room_id);
      if (active.current && result) setRoom(result);
    } catch (e) {
      if (active.current)
        setError(e instanceof Error ? e.message : "Could not complete the room action.");
    } finally {
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
  const text = (title: string) => (
    <label>
      {title}
      <textarea name="text" required maxLength={2000} />
    </label>
  );
  const select = (name: string, title: string, children: ReactNode) => (
    <label>
      {title}
      <select name={name}>{children}</select>
    </label>
  );
  const button = (action: string) => (
    <button
      type="button"
      className="park-btn park-btn--secondary park-btn--md"
      onClick={() => void act(action)}
    >
      {action}
    </button>
  );
  const form = (action: string, children: ReactNode, disabled = false) => (
    <form
      key={action === "Confirm change" ? proposal?.proposal_id : action}
      onSubmit={submit(action)}
    >
      <fieldset disabled={disabled}>
        {children}
        <button
          type="submit"
          className={`park-btn park-btn--${action === "Confirm change" ? "secondary" : "primary"} park-btn--md`}
        >
          {action}
        </button>
      </fieldset>
    </form>
  );
  const leaders =
    people
      ?.filter((a) => a.rank === "director" || (a.rank === "lead" && a.district))
      .map((a) => a.id) ?? [];
  const transcript = room?.turns
    .map((t) =>
      [
        ["Turn", t.turn, "·", label(t.to), "·", t.mode].join(" "),
        t.text ?? "Question unavailable",
        t.reply ? (t.reply.text ?? "No reply was produced.") : "Reply pending. Refresh to check.",
        t.reply ? [OUTCOME[t.reply.outcome], t.reply.units.length, "cited units"].join(" · ") : "",
      ].join("\n"),
    )
    .join("\n\n");
  return (
    <section className="park-meeting-hall" aria-label="Meeting Hall">
      <h2>Meeting Hall</h2>
      {error ? <p role="alert">{error}</p> : null}
      {!people && !error ? <p>Loading recorded attendees…</p> : null}
      <fieldset disabled={busy}>
        {people && !room ? (
          lead ? (
            form(
              "Convene",
              <>
                <label>
                  Lead
                  <select value={lead} onChange={(e) => setLead(e.target.value)}>
                    {options(leaders)}
                  </select>
                </label>
                <fieldset key={lead}>
                  <legend>Invite agents (up to seven)</legend>
                  {choices.map((a) => (
                    <label key={a.id}>
                      <input type="checkbox" name="agents" value={a.id} />
                      {label(a.id)}
                    </label>
                  ))}
                </fieldset>
              </>,
            )
          ) : (
            <p>No recorded lead is available for this world.</p>
          )
        ) : null}
        {room ? (
          <>
            <p>
              {room.credits_spent} / {room.credit_cap} credits
            </p>
            <p>
              {open
                ? [room.turns.length, " / ", room.max_turns, " turns"].join("")
                : `Adjourned · ${room.reason ? CLOSED[room.reason] : "Reason unavailable"}`}
            </p>
            {button("Refresh replies")}
            <pre>{transcript}</pre>
            {Object.entries(confirmed).map(([id, status]) => (
              <output key={id}>{status}</output>
            ))}
            {proposal && open
              ? form(
                  "Confirm change",
                  <>
                    <p>
                      Change from turn {proposedTurn?.turn} · {label(proposedTurn?.to ?? room.lead)}
                    </p>
                    <p>Units: {proposal.units.join(", ")}</p>
                    {text("Change wording")}
                  </>,
                )
              : null}
            {open ? (
              <>
                {form(
                  "Send question",
                  <>
                    {select("to", "Ask", options([room.lead, ...room.agents]))}
                    {select(
                      "mode",
                      "Mode",
                      ["quick", "thinking"].map((m) => (
                        <option key={m} value={m}>
                          {m === "quick" ? "Quick" : "Thinking"}
                        </option>
                      )),
                    )}
                    {text("Question")}
                  </>,
                  room.turns.some((t) => !t.reply) || room.turns.length >= room.max_turns,
                )}
                {button("Adjourn")}
              </>
            ) : null}
          </>
        ) : null}
      </fieldset>
    </section>
  );
}
