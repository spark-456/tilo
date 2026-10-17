import { type FormEvent, useEffect, useRef, useState } from "react";
import type { PeopleList, PeopleRow } from "../../api/live/peopleLists";

type LoadState = "loading" | "failed" | "unavailable" | PeopleList;
type CreatePin = (title: string, teamId: string | null, idempotencyKey: string) => Promise<void>;

function PinCard({ pin, tone }: { pin: PeopleRow; tone: number }) {
  return (
    <article className="park-agenda-livepin" data-pin={pin.id} data-pin-tone={tone}>
      <span className="park-agenda-livepin__tack" aria-hidden="true" />
      <strong>{pin.title}</strong>
      {pin.body ? <p>{pin.body}</p> : null}
      <span className="park-agenda-livepin__scope">
        {pin.scope === "Personal" ? "My pin" : "Team pin"}
      </span>
    </article>
  );
}

function Board({
  title,
  rows,
  state,
  teamId,
  createPin,
  onPinCreated,
}: {
  title: "My board" | "Team board";
  rows: readonly PeopleRow[];
  state: LoadState;
  teamId: string | null;
  createPin: CreatePin | null;
  onPinCreated: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const idempotencyKey = useRef<string | null>(null);
  const personal = title === "My board";
  const targetTeam = personal ? null : teamId;
  const canAdd = createPin !== null && (personal || teamId !== null) && state !== "unavailable";
  const hintId = personal ? "agenda-my-pin-hint" : "agenda-team-pin-hint";

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const titleText = draft.trim();
    if (!titleText || !createPin || !canAdd || busy) return;
    idempotencyKey.current ??= crypto.randomUUID();
    setBusy(true);
    setMessage("");
    try {
      await createPin(titleText, targetTeam, idempotencyKey.current);
      idempotencyKey.current = null;
      setDraft("");
      setMessage("Pin saved");
      onPinCreated();
    } catch {
      setMessage("Could not confirm the pin was saved. Check this board before trying again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="park-agenda-liveboard"
      aria-label={title}
      data-board={personal ? "me" : "team"}
    >
      <div className="park-agenda-liveboard__head">
        <h3>{title}</h3>
        <span>{`${rows.length} ${rows.length === 1 ? "pin" : "pins"}`}</span>
      </div>
      <div className="park-agenda-cork park-agenda-livecork" data-cork-board="">
        {state === "loading" ? <p className="park-agenda-liveboard__empty">Loading pins…</p> : null}
        {state === "unavailable" ? (
          <p className="park-agenda-liveboard__empty">
            Pins appear here when your board is connected.
          </p>
        ) : null}
        {state === "failed" ? (
          <p className="park-agenda-liveboard__empty">
            Could not load pins. Try again in a moment.
          </p>
        ) : null}
        {typeof state === "object" && rows.length === 0 ? (
          <p className="park-agenda-liveboard__empty">Nothing pinned here yet.</p>
        ) : null}
        {rows.map((pin, index) => (
          <PinCard key={pin.id} pin={pin} tone={index % 4} />
        ))}
        <form className="park-agenda-liveboard__add" onSubmit={(event) => void save(event)}>
          <label className="park-agenda-sr" htmlFor={`agenda-pin-${personal ? "me" : "team"}`}>
            {`Pin to ${title}`}
          </label>
          <input
            id={`agenda-pin-${personal ? "me" : "team"}`}
            aria-label={`Pin to ${title}`}
            value={draft}
            maxLength={120}
            placeholder="Write a note…"
            onChange={(event) => {
              idempotencyKey.current = null;
              setDraft(event.target.value);
              setMessage("");
            }}
            disabled={!canAdd || busy}
          />
          <button
            type="submit"
            disabled={!canAdd || !draft.trim() || busy}
            aria-describedby={!personal && !teamId ? hintId : undefined}
          >
            {busy ? "Saving…" : "Add a pin"}
          </button>
        </form>
        {!personal && !teamId ? (
          <p id={hintId} className="park-agenda-liveboard__hint">
            Join a team to add a team pin.
          </p>
        ) : null}
        {message ? <output className="park-agenda-liveboard__message">{message}</output> : null}
      </div>
    </section>
  );
}

export function LivePinboards({
  load,
  teamIds,
  createPin,
  onPinCreated,
}: {
  load: (() => Promise<{ data: PeopleList }>) | null;
  teamIds: readonly string[];
  createPin: CreatePin | null;
  onPinCreated: () => void;
}) {
  const [state, setState] = useState<LoadState>(load ? "loading" : "unavailable");
  const [attempt, setAttempt] = useState(0);
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt is the explicit retry trigger.
  useEffect(() => {
    let current = true;
    if (!load) {
      setState("unavailable");
      return undefined;
    }
    setState("loading");
    load().then(
      (result) => current && setState(result.data),
      () => current && setState("failed"),
    );
    return () => {
      current = false;
    };
  }, [load, attempt]);
  const rows = typeof state === "object" ? state.rows : [];
  const retry =
    state === "failed" ? (
      <button
        type="button"
        className="park-agenda-liveboards__retry"
        onClick={() => setAttempt((n) => n + 1)}
      >
        Try again
      </button>
    ) : null;
  return (
    <section aria-label="Boards" className="park-agenda-liveboards">
      <div className="park-agenda-liveboards__head">
        <div>
          <h2>Boards</h2>
          <p>Your personal and team pins, together with the week.</p>
        </div>
        {retry}
      </div>
      <div className="park-agenda-liveboards__grid">
        <Board
          title="My board"
          rows={rows.filter((pin) => pin.scope === "Personal")}
          state={state}
          teamId={null}
          createPin={createPin}
          onPinCreated={onPinCreated}
        />
        <Board
          title="Team board"
          rows={rows.filter((pin) => pin.scope !== "Personal")}
          state={state}
          teamId={teamIds[0] ?? null}
          createPin={createPin}
          onPinCreated={onPinCreated}
        />
      </div>
    </section>
  );
}
