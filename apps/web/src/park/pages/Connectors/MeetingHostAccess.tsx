// M1 (FR-MTG-09, FR-CON-02; ADR-0024 decisions 1 to 5, ADR-0035 LC-01 to LC-06): "Sign in the meeting host". Hosted
// meetings are created by the meeting bot's OWN Google account (connector `meeting_host`, one scope), not the person's.
// The button starts the same connect flow as the Google account section (the flow saves Google's state in this tab
// before leaving; the callback page finishes it), so nothing here touches a code, state or token. The status is
// whatever the live `GET /v1/connectors` read said: before it, or when it is not confirmed, nothing is "connected".
// With no flow (a demo or replay session, or no API) the section says it needs a real sign-in and offers no button.
import { useCallback, useEffect, useState } from "react";
import {
  type ConnectFlow,
  HOST_NOT_CONNECTED_TEXT,
  type HostState,
  MEETING_HOST,
  MEETING_HOST_CAPABILITIES,
} from "../../../api/connect";

const STATE_TEXT: Record<HostState, string> = {
  not_configured: HOST_NOT_CONNECTED_TEXT,
  connected: "Connected",
  attention: "Needs attention: the sign-in has expired or is about to",
  available: "Not connected",
  unknown: "Tilo could not confirm the connection, so none is shown",
};
const WHO =
  "Sign in as the meeting bot's own Google account, not your own. Tilo never sees its password. It asks for one permission: to create calendar events that account owns, with a Google Meet link.";
const WARNING =
  "This ends Tilo's access to the meeting host account. Invitations Tilo has not sent yet will not be sent. Meetings already created stay as they are.";
const NOTES = {
  start:
    "Tilo could not start the meeting host sign-in. Nothing was changed. Check that your browser allows this site to keep data for the tab, then try again.",
  blocked: "Your browser did not open Google's sign-in. Nothing was changed, so please try again.",
  nothing: "The meeting host already has that access.",
  off: "Tilo could not disconnect the meeting host. Nothing was changed, so please try again.",
  done: "The meeting host is disconnected. Tilo can no longer create meetings with it.",
  pending:
    "Google did not confirm that Tilo's access ended. To be sure, sign in to the meeting host account at Google and remove Tilo under Google Account > Security > Third-party access.",
} as const;

export function MeetingHostAccess({ flow }: { flow: ConnectFlow | null }) {
  const [state, setState] = useState<HostState | null>(null); // null: not read yet
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const load = useCallback(() => {
    if (flow === null) return;
    setState(null);
    flow.meetingHost().then(setState, () => setState("unknown"));
  }, [flow]);
  useEffect(() => {
    load();
  }, [load]);

  const head = (
    <div className="park-connectors-sechead">
      <span className="park-connectors-sectitle">Meeting host account</span>
      <span className="park-connectors-count">Hosted meetings come from Tilo's own account.</span>
    </div>
  );
  if (flow === null) {
    return (
      <section className="park-connectors-section" aria-label="Meeting host account">
        {head}
        <output className="park-connectors-note">
          Signing in the meeting host needs a real Tilo sign-in. This demo or replay session cannot
          connect a Google account.
        </output>
      </section>
    );
  }

  if (state === "not_configured") {
    return (
      <section className="park-connectors-section" aria-label="Meeting host account">
        <p>{HOST_NOT_CONNECTED_TEXT}</p>
      </section>
    );
  }

  const signIn = () => {
    setBusy(true);
    setNote(null);
    flow.start(MEETING_HOST, MEETING_HOST_CAPABILITIES).then((r) => {
      if (r.kind === "redirect") {
        try {
          flow.open(r.url); // the page leaves here; if it cannot, the person is told and may retry
          return;
        } catch {
          setNote(NOTES.blocked);
        }
      } else {
        setNote(r.kind === "nothing_missing" ? NOTES.nothing : NOTES.start);
        if (r.kind === "nothing_missing") load();
      }
      setBusy(false);
    });
  };
  const disconnect = () => {
    setBusy(true);
    setConfirm(false);
    flow.disconnect(MEETING_HOST).then((result) => {
      setBusy(false);
      setNote(
        result === "done" ? NOTES.done : result === "revoke_pending" ? NOTES.pending : NOTES.off,
      );
      if (result !== "failed") load();
    });
  };

  const action = (label: string, run: () => void) => (
    <button type="button" className="park-connectors-connect" disabled={busy} onClick={run}>
      {busy && label.startsWith("Sign in") ? "Opening Google" : label}
    </button>
  );
  return (
    <section className="park-connectors-section" aria-label="Meeting host account">
      {head}
      <p className="park-connectors-count">{WHO}</p>
      <div className="park-connectors-availgrid">
        <div className="park-connectors-avail">
          <span className="park-connectors-avail-mono">M</span>
          <span className="park-connectors-avail-names">
            <span className="park-connectors-avail-name">Tilo meeting host</span>
            <span className="park-connectors-avail-blurb">
              {state === null ? "Checking" : STATE_TEXT[state]}
            </span>
          </span>
          {state === "available" ? action("Sign in the meeting host", signIn) : null}
          {state === "attention" ? action("Sign in again", signIn) : null}
          {state === "connected" || state === "attention" ? (
            <button
              type="button"
              className="park-connectors-connect"
              disabled={busy}
              onClick={() => setConfirm(true)}
            >
              Disconnect
            </button>
          ) : null}
          {state === "unknown" ? action("Check again", load) : null}
        </div>
      </div>
      {confirm ? (
        <div
          className="park-connectors-note"
          role="alertdialog"
          aria-label="Disconnect meeting host"
        >
          <p>{WARNING}</p>
          <button type="button" className="park-connectors-disconnect" onClick={disconnect}>
            Disconnect the meeting host
          </button>
          <button
            type="button"
            className="park-connectors-connect"
            onClick={() => setConfirm(false)}
          >
            Keep connected
          </button>
        </div>
      ) : null}
      {note !== null ? <output className="park-connectors-note">{note}</output> : null}
    </section>
  );
}
