// FR-MTG-01, FR-MTG-09, FR-MTG-10 (ADR-0024, MEET-SIMPLE): meet with Tilo from the Agenda in one click.
// "Meet with Tilo now" makes the Meet, invites only the person who clicked, opens it and sends Tilo in. "Schedule with
// others" is one small dialog whose Confirm button is the person's approval. The person's own click is the explicit
// human action; the API records it as the approval and sends exactly the people shown. Every line is one the API's
// reply supports; nothing retries by itself except the API's own wait for a cold bot, and there is no progress bar (HR-1).
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import type { HostState } from "../../../api/connect";
import { displayApiError } from "../../../api/http";
import { ENDED_TEXT, type MeetingHostApi } from "../../api/live/meetingHost";
import { AppLink } from "../../shared/AppLink";
import {
  type HostForm,
  type HostableRow,
  LENGTHS,
  MEET_NOW_NOTICE,
  type MeetTab,
  NOTICE_TEXT,
  type Picked,
  attendOffered,
  clockMs,
  hostFormError,
  later,
  openMeetTab,
} from "../../shared/hostMeetingRules";

type Flow =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "joining"; id: string }
  | { phase: "ended"; text: string }
  | { phase: "retry"; id: string }
  | { phase: "failed"; text: string }
  | { phase: "scheduled"; names: string[] };

const JOIN_FAILED = "Tilo could not join the meeting.";
const WRAP_UP =
  'In the Meet chat, type "Tilo leave". Tilo leaves and your minutes can be made below.';

/** "Meet with Tilo": shown only when the meeting host account is Connected (`GET /v1/connectors`). */
export function HostMeeting({
  api,
  hostState,
  now = clockMs,
  onChanged,
}: {
  api: MeetingHostApi;
  hostState: () => Promise<HostState>;
  now?: () => number;
  onChanged?: () => void;
}) {
  const [conn, setConn] = useState<HostState | null>(null);
  const [flow, setFlow] = useState<Flow>({ phase: "idle" });
  const [dialog, setDialog] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const [wrap, setWrap] = useState(false);
  // One failed or unconfirmed read must not stick: "Check again" reads it afresh (the same read the Connectors page makes).
  const read = useCallback(() => {
    hostState().then(setConn, () => setConn("unknown"));
  }, [hostState]);
  useEffect(() => read(), [read]);
  if (conn === null) return null;
  if (conn !== "connected")
    return (
      <p data-testid="host-meeting-gate">
        {conn === "unknown" ? "Tilo could not confirm the meeting host. " : ""}
        <AppLink to="/connectors">Sign in the meeting host first</AppLink>
        {conn === "unknown" ? (
          <>
            {" "}
            <button type="button" className="secondary" onClick={read}>
              Check again
            </button>
          </>
        ) : null}
      </p>
    );

  const attend = async (id: string) => {
    setFlow({ phase: "joining", id });
    try {
      const r = await api.attend(id);
      setFlow({
        phase: "ended",
        text: (r.reason && ENDED_TEXT[r.reason]) || `The meeting is now ${r.status}.`,
      });
    } catch {
      setFlow({ phase: "retry", id }); // the invitation and the meeting stand: only the joining is asked again
    }
    setWrap(false);
    onChanged?.();
  };
  const meetNow = async () => {
    const tab: MeetTab | null = openMeetTab(); // opened on the click, so the browser allows it
    setLink(null);
    setFlow({ phase: "starting" });
    let id: string | null = null;
    let sent = false;
    try {
      const { you } = await api.people();
      id = await api.createNow(now(), crypto.randomUUID());
      await api.world(id);
      await api.start(id, [you]);
      sent = true;
      const j = await api.join(id);
      if (tab) tab.go(j.url);
      else setLink(j.url);
    } catch (e) {
      tab?.close();
      if (id !== null && !sent) await api.remove(id).catch(() => undefined);
      setFlow({ phase: "failed", text: displayApiError(e) });
      return;
    }
    await attend(id);
  };
  const scheduled = async (picked: Picked[], f: HostForm) => {
    const { you } = await api.people();
    const id = await api.create(f, crypto.randomUUID(), picked);
    try {
      await api.world(id);
      await api.start(id, [you, ...picked.map((p) => p.id)]);
    } catch (e) {
      await api.remove(id).catch(() => undefined);
      throw e;
    }
    setDialog(false);
    setFlow({ phase: "scheduled", names: picked.map((p) => p.name) });
    onChanged?.();
  };

  const busy = flow.phase === "starting" || flow.phase === "joining";
  return (
    <div className="park-agenda-hostbox" aria-label="Meet with Tilo">
      <div className="park-agenda-hostactions">
        <button type="button" disabled={busy} onClick={() => void meetNow()}>
          Meet with Tilo now
        </button>
        <button type="button" className="secondary" disabled={busy} onClick={() => setDialog(true)}>
          Schedule with others
        </button>
      </div>
      <small>{MEET_NOW_NOTICE}</small>
      {flow.phase === "starting" ? <output>Starting…</output> : null}
      {flow.phase === "joining" ? (
        <output>
          Tilo is joining… Admit Tilo notetaker in Meet if it asks. Keep this tab open.
        </output>
      ) : null}
      {flow.phase === "joining" ? (
        <div>
          <button type="button" className="secondary" onClick={() => setWrap(true)}>
            Wrap up
          </button>
          {wrap ? <p>{WRAP_UP}</p> : null}
        </div>
      ) : null}
      {link && busy ? (
        <a href={link} target="_blank" rel="noopener noreferrer">
          Open the call in Meet
        </a>
      ) : null}
      {flow.phase === "retry" ? (
        <div role="alert">
          <p>{JOIN_FAILED}</p>
          <button type="button" onClick={() => void attend(flow.id)}>
            Try again
          </button>
        </div>
      ) : null}
      {flow.phase === "failed" ? <p role="alert">{flow.text}</p> : null}
      {flow.phase === "ended" ? (
        <output>{`${flow.text} Your minutes can be made from the meeting below.`}</output>
      ) : null}
      {flow.phase === "scheduled" ? (
        <output>
          {`Scheduled. Invitations went to you${flow.names.length ? `, ${flow.names.join(", ")}` : ""}. Bring Tilo in from the meeting below when it starts.`}
        </output>
      ) : null}
      {dialog ? (
        <ScheduleDialog
          api={api}
          now={now}
          onCancel={() => setDialog(false)}
          onConfirm={scheduled}
        />
      ) : null}
    </div>
  );
}

/** One small dialog. Its Confirm button is the person's approval, and it names everyone who will be invited. */
function ScheduleDialog({
  api,
  now,
  onCancel,
  onConfirm,
}: {
  api: MeetingHostApi;
  now: () => number;
  onCancel: () => void;
  onConfirm: (picked: Picked[], f: HostForm) => Promise<void>;
}) {
  const [f, setF] = useState<HostForm>({ title: "", start: "", minutes: 30, attested: false });
  const [people, setPeople] = useState<Picked[] | null>(null);
  const [you, setYou] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    api.people().then(
      (r) => {
        if (!live) return;
        setYou(r.you);
        setPeople(r.people.filter((p) => p.id !== r.you));
      },
      () => live && setErr("Tilo could not read your people list. Close this and try again."),
    );
    return () => {
      live = false;
    };
  }, [api]);
  const picked = (people ?? []).filter((p) => chosen.includes(p.id));
  const submit = async () => {
    const bad = hostFormError(f, now());
    if (bad) return setErr(bad);
    setBusy(true);
    setErr("");
    try {
      await onConfirm(picked, f);
    } catch (e) {
      setErr(`Nothing was sent. ${displayApiError(e)}`);
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
      aria-label="Schedule with others"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      onKeyDown={(e) => e.key === "Escape" && onCancel()}
    >
      {field(
        "Title",
        <input
          name="title"
          value={f.title}
          maxLength={120}
          onChange={(e) => setF({ ...f, title: e.target.value })}
        />,
      )}
      {field(
        "Starts (your local time)",
        <input
          name="start"
          type="datetime-local"
          value={f.start}
          onChange={(e) => setF({ ...f, start: e.target.value })}
        />,
      )}
      {field(
        "Length",
        <select value={f.minutes} onChange={(e) => setF({ ...f, minutes: Number(e.target.value) })}>
          {LENGTHS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>,
      )}
      <fieldset className="park-agenda-hostpeople">
        <legend>Invite</legend>
        {people === null && !err ? <output>Loading…</output> : null}
        {people?.length === 0 ? <p>No one else is on your team yet.</p> : null}
        {(people ?? []).map((p) => (
          <label key={p.id} className="park-agenda-hostnotice">
            <input
              type="checkbox"
              checked={chosen.includes(p.id)}
              onChange={(e) =>
                setChosen(e.target.checked ? [...chosen, p.id] : chosen.filter((c) => c !== p.id))
              }
            />
            <span>{p.name}</span>
          </label>
        ))}
      </fieldset>
      <p data-testid="host-invite-list">
        {`Invitations will go to: you${picked.length ? `, ${picked.map((p) => p.name).join(", ")}` : ""}. No one else.`}
      </p>
      <label className="park-agenda-hostnotice">
        <input
          type="checkbox"
          checked={f.attested}
          onChange={(e) => setF({ ...f, attested: e.target.checked })}
        />
        <span>{NOTICE_TEXT}</span>
      </label>
      {err ? <p role="alert">{err}</p> : null}
      <div className="park-agenda-hostactions">
        <button type="submit" disabled={busy || people === null || !you}>
          Confirm and send invitations
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {busy ? <output>Working…</output> : null}
    </form>
  );
}

type Held =
  | { phase: "idle" }
  | { phase: "held" }
  | { phase: "ended"; text: string }
  | { phase: "refused"; text: string };

/** On a scheduled meeting from 10 minutes before its start until its end: bring Tilo in, or open the call. */
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
      setHeld({ phase: "refused", text: displayApiError(e) }); // asked again only by the person
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
          Bring Tilo in
        </button>
      ) : null}
      {held.phase === "held" ? (
        <output>Tilo is joining… Admit Tilo notetaker in Meet. Keep this tab open.</output>
      ) : null}
      {held.phase === "ended" ? <output>{held.text}</output> : null}
      {held.phase === "refused" ? (
        <div role="alert">
          <p>{held.text}</p>
          <button type="button" onClick={() => void send()}>
            Try again
          </button>
        </div>
      ) : null}
      <button type="button" onClick={() => void openMeet()}>
        Open the call
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
