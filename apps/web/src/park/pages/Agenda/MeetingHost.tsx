// FR-MTG-01, FR-MTG-09, FR-MTG-10 (ADR-0024): host a Google Meet with the Tilo notetaker, and send Tilo to it.
// Every line is one the API's reply supports; nothing retries by itself, and there is no progress bar (HR-1).
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { HostState } from "../../../api/connect";
import { displayApiError } from "../../../api/http";
import { ENDED_TEXT, type MeetingHostApi } from "../../api/live/meetingHost";
import { AppLink } from "../../shared/AppLink";
import {
  type HostForm,
  type HostableRow,
  LENGTHS,
  NOTICE_TEXT,
  attendOffered,
  clockMs,
  hostFormError,
  later,
} from "../../shared/hostMeetingRules";

interface Made {
  id: string | null;
  world: boolean;
}

/** "Host a meeting with Tilo": shown only when the meeting host account is Connected (`GET /v1/connectors`). */
export function HostMeeting({
  api,
  hostState,
  now = clockMs,
}: { api: MeetingHostApi; hostState: () => Promise<HostState>; now?: () => number }) {
  const [conn, setConn] = useState<HostState | null>(null);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState<HostForm>({ title: "", start: "", minutes: 30, attested: false });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const made = useRef<Made>({ id: null, world: false });
  const [key] = useState(() => crypto.randomUUID());
  useEffect(() => {
    hostState().then(setConn, () => setConn("unknown"));
  }, [hostState]);
  if (conn === null) return null;
  if (conn !== "connected")
    return (
      <p data-testid="host-meeting-gate">
        {conn === "unknown" ? "Tilo could not confirm the meeting host. " : ""}
        <AppLink to="/connectors">Sign in the meeting host first</AppLink>
      </p>
    );
  if (done)
    return (
      <output data-testid="host-meeting-done">
        Approve the invitation in Needs you. Nothing is sent until you approve it.{" "}
        <AppLink to="/needs-you">Open Needs you</AppLink>
      </output>
    );
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)}>
        Host a meeting with Tilo
      </button>
    );
  const started = made.current.id !== null; // fields are fixed once the meeting exists
  const submit = async () => {
    const bad = hostFormError(f, now());
    if (bad && !started) return setErr(bad);
    setBusy(true);
    setErr("");
    let created = started;
    try {
      let id = made.current.id;
      if (id === null) {
        id = await api.create(f, key);
        made.current.id = id;
      }
      created = true;
      if (!made.current.world) {
        await api.world(id);
        made.current.world = true;
      }
      await api.host(id);
      setDone(true);
    } catch (e) {
      setErr(
        `${created ? "The meeting was created but not hosted yet." : "Nothing was created."} ${displayApiError(e)}`,
      );
    } finally {
      setBusy(false);
    }
  };
  const field = (label: string, input: ReactNode) => (
    // biome-ignore lint/a11y/noLabelWithoutControl: the control is the `input` argument, nested here
    <label className="park-agenda-hostfield">
      <span>{label}</span>
      {input}
    </label>
  );
  return (
    <form
      className="park-agenda-hostform"
      aria-label="Host a meeting with Tilo"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      {field(
        "Title",
        <input
          name="title"
          value={f.title}
          maxLength={120}
          disabled={started}
          onChange={(e) => setF({ ...f, title: e.target.value })}
        />,
      )}
      {field(
        "Starts (your local time)",
        <input
          name="start"
          type="datetime-local"
          value={f.start}
          disabled={started}
          onChange={(e) => setF({ ...f, start: e.target.value })}
        />,
      )}
      {field(
        "Length",
        <select
          value={f.minutes}
          disabled={started}
          onChange={(e) => setF({ ...f, minutes: Number(e.target.value) })}
        >
          {LENGTHS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>,
      )}
      <label className="park-agenda-hostnotice">
        <input
          type="checkbox"
          checked={f.attested}
          disabled={started}
          onChange={(e) => setF({ ...f, attested: e.target.checked })}
        />
        <span>{NOTICE_TEXT}</span>
      </label>
      {err ? <p role="alert">{err}</p> : null}
      <button type="submit" disabled={busy}>
        {started ? "Try again" : "Send for approval"}
      </button>
      {busy ? <output>Working…</output> : null}
    </form>
  );
}

type Held =
  | { phase: "idle" }
  | { phase: "held" }
  | { phase: "ended"; text: string }
  | { phase: "refused"; text: string };

/** On a hosted, scheduled meeting from 10 minutes before its start until its end: send Tilo, or open Meet. */
export function MeetingAttend({
  id,
  row,
  api,
  now = clockMs,
  onChanged,
}: {
  id: string;
  row: HostableRow;
  api: MeetingHostApi;
  now?: () => number;
  onChanged?: () => void;
}) {
  const [held, setHeld] = useState<Held>({ phase: "idle" });
  const [link, setLink] = useState<string | null>(null);
  const [linkErr, setLinkErr] = useState("");
  const cancel = useRef<() => void>(() => undefined);
  useEffect(() => () => cancel.current(), []);
  if (held.phase === "idle" && link === null && !attendOffered(row, now())) return null;
  const send = async () => {
    setHeld({ phase: "held" });
    try {
      const r = await api.attend(id);
      setHeld({
        phase: "ended",
        text: (r.reason && ENDED_TEXT[r.reason]) || `The meeting is now ${r.status}.`,
      });
    } catch (e) {
      setHeld({ phase: "refused", text: displayApiError(e) }); // never retried by itself
    }
    onChanged?.();
  };
  const openMeet = async () => {
    setLinkErr("");
    try {
      const j = await api.join(id);
      setLink(j.url); // held in memory only, dropped when the server's expiry passes
      cancel.current();
      cancel.current = later(() => setLink(null), Math.max(0, j.expires - now()));
    } catch (e) {
      setLink(null);
      setLinkErr(displayApiError(e));
    }
  };
  return (
    <div aria-label="Tilo in the meeting">
      {held.phase === "idle" ? (
        <button type="button" onClick={() => void send()}>
          Send Tilo to the meeting
        </button>
      ) : null}
      {held.phase === "held" ? (
        <output>
          Tilo is asking to join as Tilo notetaker. Admit it in Meet. Keep this tab open.
        </output>
      ) : null}
      {held.phase === "ended" ? <output>{held.text}</output> : null}
      {held.phase === "refused" ? <p role="alert">{held.text}</p> : null}
      <button type="button" onClick={() => void openMeet()}>
        Open Meet
      </button>
      {link ? (
        <a href={link} target="_blank" rel="noopener noreferrer">
          Open the call in Meet
        </a>
      ) : null}
      {linkErr ? <p role="alert">{linkErr}</p> : null}
    </div>
  );
}
