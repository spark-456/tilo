import { useEffect, useState } from "react";
import { displayApiError } from "../../../api/http";
import type { MeetingHostApi } from "../../api/live/meetingHost";
import { AppLink } from "../../shared/AppLink";
import {
  type HostForm,
  LENGTHS,
  NOTICE_TEXT,
  type Picked,
  hostFormError,
  refusedBeforeSend,
} from "../../shared/hostMeetingRules";
import { Modal } from "./Modal";

const localInput = (value: string): string => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

export function ScheduleWithOthersDialog({
  api,
  start,
  minutes,
  title = "",
  onClose,
  onScheduled,
}: {
  api: MeetingHostApi | null;
  start: string;
  minutes: number;
  title?: string;
  onClose: () => void;
  onScheduled: () => void;
}) {
  const [form, setForm] = useState<HostForm>({
    title,
    start: localInput(start),
    minutes: (LENGTHS as readonly number[]).includes(minutes) ? minutes : 15,
    attested: false,
  });
  const [people, setPeople] = useState<Picked[] | null>(null);
  const [you, setYou] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!api) return;
    let live = true;
    api.people().then(
      (reply) => {
        if (!live) return;
        setYou(reply.you);
        setPeople(reply.people.filter((person) => person.id !== reply.you));
      },
      () => live && setError("Tilo could not read your people list. Close this and try again."),
    );
    return () => {
      live = false;
    };
  }, [api]);

  const picked = (people ?? []).filter((person) => chosen.includes(person.id));
  const confirm = async () => {
    if (!api) return;
    const invalid = hostFormError(form, Date.now());
    if (invalid) return setError(invalid);
    if (!you || people === null || busy) return;
    setBusy(true);
    setError("");
    let id: string | null = null;
    try {
      id = await api.create(form, crypto.randomUUID(), picked);
      await api.world(id);
      await api.start(id, [you, ...picked.map((person) => person.id)]);
      onScheduled();
      onClose();
    } catch (reason) {
      if (id && refusedBeforeSend(reason)) await api.remove(id).catch(() => undefined);
      setError(
        id && !refusedBeforeSend(reason)
          ? "The meeting may already be scheduled. Check Meetings before trying again."
          : `Nothing was sent. ${displayApiError(reason)}`,
      );
      setBusy(false);
    }
  };

  return (
    <Modal label="Schedule with others" onClose={onClose}>
      {!api ? (
        <div className="park-agenda-hostform">
          <h2>Schedule with others</h2>
          <p>Connect the meeting host before scheduling a meeting.</p>
          <AppLink to="/connectors">Connect the meeting host</AppLink>
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </div>
      ) : (
        <form
          className="park-agenda-hostform"
          aria-label="Schedule with others"
          onSubmit={(event) => {
            event.preventDefault();
            void confirm();
          }}
        >
          <h2>Schedule with others</h2>
          <label className="park-agenda-hostfield">
            <span>Title</span>
            <input
              name="title"
              value={form.title}
              maxLength={120}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </label>
          <label className="park-agenda-hostfield">
            <span>Starts (your local time)</span>
            <input
              name="start"
              type="datetime-local"
              value={form.start}
              onChange={(e) => setForm({ ...form, start: e.target.value })}
            />
          </label>
          <label className="park-agenda-hostfield">
            <span>Length</span>
            <span className="park-agenda-hostselect">
              <select
                value={form.minutes}
                onChange={(e) => setForm({ ...form, minutes: Number(e.target.value) })}
              >
                {LENGTHS.map((length) => (
                  <option key={length} value={length}>
                    {length} minutes
                  </option>
                ))}
              </select>
            </span>
          </label>
          <fieldset>
            <legend>Invite people</legend>
            {people === null ? <output>Loading people…</output> : null}
            {people?.length === 0 ? <p>No one else is on your team yet.</p> : null}
            {people?.map((person) => (
              <label key={person.id} className="park-agenda-hostnotice">
                <input
                  type="checkbox"
                  checked={chosen.includes(person.id)}
                  onChange={(event) =>
                    setChosen(
                      event.target.checked
                        ? [...chosen, person.id]
                        : chosen.filter((id) => id !== person.id),
                    )
                  }
                />
                <span>{person.name}</span>
              </label>
            ))}
          </fieldset>
          <p>{`Invitations will go to: you${picked.length ? `, ${picked.map((person) => person.name).join(", ")}` : ""}. No one else.`}</p>
          <label className="park-agenda-hostnotice">
            <input
              type="checkbox"
              checked={form.attested}
              onChange={(e) => setForm({ ...form, attested: e.target.checked })}
            />
            <span>{NOTICE_TEXT}</span>
          </label>
          {error ? <p role="alert">{error}</p> : null}
          <div className="park-agenda-hostactions">
            <button type="submit" disabled={busy || people === null || !you}>
              Confirm and send invitations
            </button>
            <button type="button" className="secondary" onClick={onClose}>
              Cancel
            </button>
          </div>
          {busy ? <output>Working…</output> : null}
        </form>
      )}
    </Modal>
  );
}
