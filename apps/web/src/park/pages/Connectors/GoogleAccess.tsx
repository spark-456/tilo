// ADR-0035 L4 (LC-01, LC-02, LC-06; FR-CON-02): the person's own Google sign-in, live only. It renders when the page is
// given a live ConnectFlow (a configured deployment, a signed-in Google person); the fixture world and a demo session
// have none, so nothing here runs there. Connect asks tilo-api for Google's link, saves its state (the flow does that),
// then opens the link; the callback page finishes it. Disconnect warns first that Google keeps one sign-in for Gmail,
// Drive and Calendar, so all three end together. Plain words only: no code, no state and no Google text is shown.
import { useCallback, useEffect, useState } from "react";
import {
  type ConnectFlow,
  type ConnectionRow,
  GOOGLE_PERSON_CONNECTORS,
} from "../../../api/connect";
import { BrandIcon } from "./BrandIcon";

const MONO: Record<string, string> = { gmail: "G", google_drive: "D", google_calendar: "C" };
const READ = {
  gmail: {
    label: "Read mail",
    capabilities: ["read", "search"],
    scope: "https://www.googleapis.com/auth/gmail.readonly",
    copy: "Agents may search and read your mail.",
  },
  google_drive: {
    label: "Read Drive",
    capabilities: ["read", "list"],
    scope: "https://www.googleapis.com/auth/drive.file",
    copy: "Agents may list and read files you pick for Tilo and files Tilo saves.",
  },
  google_calendar: {
    label: "Read calendar",
    capabilities: ["read"],
    scope: "https://www.googleapis.com/auth/calendar.readonly",
    copy: "Agents may read your calendar events.",
  },
} as const;
const STATE_TEXT = {
  connected: "Connected",
  attention: "Needs attention",
  available: "Not connected",
};
const WARNING =
  "Google keeps one sign-in for Gmail, Google Drive and Google Calendar. Disconnecting any one of them disconnects all three, and Tilo loses access to all three.";
const NOTES = {
  read: "Could not read your Google connections. Try again in a moment.",
  start: "Tilo could not start the Google sign-in. Please try again.",
  nothing: "That access is already connected.",
  off: "Tilo could not disconnect Google. Nothing was changed, so please try again.",
  done: "Google is disconnected. Gmail, Google Drive and Google Calendar are all off.",
  pending:
    "Google did not confirm that Tilo's access ended. To be sure, remove Tilo yourself under Google Account > Security > Third-party access.",
} as const;

export function GoogleAccess({ flow }: { flow: ConnectFlow }) {
  const [rows, setRows] = useState<ConnectionRow[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  const load = useCallback(() => {
    flow.list().then(
      (r) => setRows(r),
      () => {
        setRows([]);
        setNote(NOTES.read);
      },
    );
  }, [flow]);
  useEffect(() => {
    load();
  }, [load]);

  const connect = (id: keyof typeof READ) => {
    setBusy(id);
    setNote(null);
    flow.start(id, READ[id].capabilities).then((r) => {
      setBusy(null);
      if (r.kind === "redirect") flow.open(r.url);
      else {
        setNote(r.kind === "nothing_missing" ? NOTES.nothing : NOTES.start);
        if (r.kind === "nothing_missing") load();
      }
    });
  };
  const disconnect = (id: string) => {
    setBusy(id);
    setConfirm(null);
    flow.disconnect(id).then((result) => {
      setBusy(null);
      setNote(
        result === "done" ? NOTES.done : result === "revoke_pending" ? NOTES.pending : NOTES.off,
      );
      if (result !== "failed") load();
    });
  };

  const shown = rows ?? [];
  return (
    <section className="park-connectors-section" aria-label="Your Google account">
      <div className="park-connectors-sechead">
        <span className="park-connectors-sectitle">Your Google account</span>
        <span className="park-connectors-count">
          Sign in with Google. Tilo never sees your password.
        </span>
      </div>
      <p className="park-connectors-note">
        Agents may use these reads only in your own worlds. Connecting here starts Google consent;
        sharing a world later may show others outputs based on those reads.
      </p>
      <div className="park-connectors-availgrid">
        {GOOGLE_PERSON_CONNECTORS.map((id) => {
          const row = shown.find((r) => r.id === id);
          if (!row) return null;
          const on = row.state !== "available";
          const read = READ[id];
          const granted = row.scopes?.includes(read.scope);
          return (
            <div className="park-connectors-avail" key={id}>
              <span className="park-connectors-avail-mono">
                <BrandIcon id={id} mono={MONO[id] ?? row.name.charAt(0)} />
              </span>
              <span className="park-connectors-avail-names">
                <span className="park-connectors-avail-name">{row.name}</span>
                <span className="park-connectors-avail-blurb">{STATE_TEXT[row.state]}</span>
                <span className="park-connectors-avail-blurb">{read.copy}</span>
                <span className="park-connectors-avail-blurb">
                  {row.scopes === undefined && on
                    ? "Read permission not available"
                    : `${read.label} ${granted ? "granted" : "not granted"}`}
                </span>
              </span>
              {granted !== true && (!on || row.scopes !== undefined) ? (
                <button
                  type="button"
                  className="park-connectors-connect"
                  disabled={busy !== null}
                  onClick={() => connect(id)}
                >
                  {busy === id ? "Signing in" : read.label}
                </button>
              ) : null}
              {on ? (
                <button
                  type="button"
                  className="park-connectors-connect park-connectors-disconnect-action"
                  disabled={busy !== null}
                  onClick={() => setConfirm(id)}
                >
                  Disconnect
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
      {confirm !== null ? (
        <div className="park-connectors-note" role="alertdialog" aria-label="Disconnect Google">
          <p>{WARNING}</p>
          <button
            type="button"
            className="park-connectors-disconnect"
            onClick={() => disconnect(confirm)}
          >
            Disconnect all three
          </button>
          <button
            type="button"
            className="park-connectors-connect"
            onClick={() => setConfirm(null)}
          >
            Keep connected
          </button>
        </div>
      ) : null}
      {note !== null ? <output className="park-connectors-note">{note}</output> : null}
    </section>
  );
}
