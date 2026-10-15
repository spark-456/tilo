// BQ-CTX-TEAMWORLD (ADR-0040 decision 10, FR-TEAM-01/02): the world owner's "Share with team" control. The dialog
// says what sharing does before anything is changed, lists the owner's teams with the live state of each share and
// turns one on or off. A row says "Shared" only from the server's own list after the change; a failed call changes
// nothing on this page and the list is read again. The routes are the owner's alone: every other caller gets a 404,
// which is said as such. There is no sample state here: the control is not offered without a live client.
import { useEffect, useRef, useState } from "react";
import {
  REASON_WORDS,
  type ShareClient,
  type TeamShare,
  failureWords,
  isMissing,
  readShares,
  setShare,
} from "../../api/live/teamShares";
import { ORGANISATION_SETUP } from "../../api/organisationSetup";
import { useParkApi } from "../../app/context";
import { focusablesIn, handleSlackDialogKeyDown } from "../../app/slackShare";
import { Button } from "../../components";

export type Read<T> =
  | { status: "loading" }
  | { status: "failed"; message: string; missing: boolean }
  | { status: "ready"; value: T };

/** One read: loading first, then the value or a plain failure; `reload` reads again and keeps what is shown. */
export function useRead<T>(
  load: () => Promise<T>,
  keys: readonly unknown[],
): [Read<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<Read<T>>({ status: "loading" });
  // biome-ignore lint/correctness/useExhaustiveDependencies: `keys` and `attempt` are the read's identity
  useEffect(() => {
    let active = true;
    setState((s) => (s.status === "ready" ? s : { status: "loading" }));
    load().then(
      (value) => active && setState({ status: "ready", value }),
      (e: unknown) =>
        active && setState({ status: "failed", message: failureWords(e), missing: isMissing(e) }),
    );
    return () => {
      active = false;
    };
  }, [...keys, attempt]);
  return [state, () => setAttempt((n) => n + 1)];
}

/** What a shared world's readers get (ADR-0040 decision 10), said plainly before a share is made. */
export const CONSENT =
  "Sharing makes this whole world visible to every member of the team you choose: its Story, Trace, runs and artifacts, past and future, except lines only you can see. Past and future outputs may include results based on mail, calendar and Drive reads. Items added in this world from now on are visible to them too. They can read it. They cannot answer, approve, pause or share it.";

const MAX_TEAMS = 8;

function Row({
  team,
  share,
  member,
  busy,
  onChange,
}: {
  team: string;
  share: TeamShare | undefined;
  member: boolean;
  busy: boolean;
  onChange: (on: boolean) => void;
}) {
  const words = share?.inForce
    ? "Shared. Every member of this team can read this world."
    : share
      ? `Not in force. ${share.reason ? REASON_WORDS[share.reason] : ""}`
      : "Not shared.";
  return (
    <li className="park-world-teamrow">
      <span className="park-world-teamname">{team}</span>
      <span className="park-world-teamnote">{words}</span>
      {share?.inForce || (share && !member) ? (
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          aria-label={`Stop sharing with ${team}`}
          onClick={() => onChange(false)}
        >
          Stop sharing
        </Button>
      ) : member ? (
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          aria-label={`Share this world with ${team}`}
          onClick={() => onChange(true)}
        >
          Share with this team
        </Button>
      ) : null}
    </li>
  );
}

function ShareDialog({
  client,
  worldId,
  worldName,
  onClose,
}: { client: ShareClient; worldId: string; worldName: string; onClose: () => void }) {
  const api = useParkApi();
  const ref = useRef<HTMLDivElement | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState("");
  const [view, reload] = useRead(async () => {
    const team = await api.getTeam();
    const shares = team.data.setupRequired ? [] : await readShares(client, worldId);
    return {
      shares,
      setupRequired: team.data.setupRequired,
      teams: team.data.people.find((p) => p.you)?.memberships ?? null,
    };
  }, [client, worldId, api]);
  useEffect(() => {
    focusablesIn(ref.current)[0]?.focus();
  }, []);

  const change = async (team: string, on: boolean) => {
    if (busy) return;
    setBusy(team);
    setFailure("");
    try {
      await setShare(client, worldId, team, on);
    } catch (e) {
      setFailure(
        `${on ? "Could not share" : "Could not stop sharing"} with ${team}. ${failureWords(e)}`,
      );
    } finally {
      setBusy(null);
      reload(); // the list shown is always the server's, whatever the call said
    }
  };

  const mine = view.status === "ready" ? (view.value.teams ?? []).slice(0, MAX_TEAMS) : [];
  const teams =
    view.status === "ready" ? [...new Set([...mine, ...view.value.shares.map((s) => s.team)])] : [];
  return (
    <div className="park-world-slackbackdrop">
      <div
        ref={ref}
        // biome-ignore lint/a11y/useSemanticElements: custom modal dialog with focus trap and role="dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Share with team"
        className="park-world-slackdialog"
        onKeyDown={(e) => handleSlackDialogKeyDown(e, ref.current, onClose)}
      >
        <div className="park-world-slackhead">
          <div className="park-world-slacktitle">Share with team</div>
          <div className="park-world-slacksub">{worldName}</div>
        </div>
        <p className="park-world-teamnote">{CONSENT}</p>
        {view.status === "loading" ? <output>Loading your teams and shares…</output> : null}
        {view.status === "failed" ? (
          <>
            <p role="alert">
              {view.missing
                ? "Tilo could not find this world for you. Only its owner can share it."
                : view.message}
            </p>
            {view.missing ? null : (
              <Button variant="secondary" size="sm" onClick={reload}>
                Try again
              </Button>
            )}
          </>
        ) : null}
        {view.status === "ready" && view.value.setupRequired ? (
          <output>{ORGANISATION_SETUP}</output>
        ) : null}
        {view.status === "ready" && !view.value.setupRequired ? (
          <>
            {view.value.teams === null ? (
              <p role="alert">Tilo could not read which teams you belong to.</p>
            ) : null}
            {teams.length === 0 && view.value.teams !== null ? (
              <p>You are not in a team yet, so there is nobody to share this world with.</p>
            ) : null}
            <ul className="park-world-teamlist" aria-label="Teams">
              {teams.map((t) => (
                <Row
                  key={t}
                  team={t}
                  share={view.value.shares.find((s) => s.team === t)}
                  member={mine.includes(t)}
                  busy={busy !== null}
                  onChange={(on) => void change(t, on)}
                />
              ))}
            </ul>
          </>
        ) : null}
        {failure ? <p role="alert">{failure}</p> : null}
        <div className="park-world-slackactions">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}

/** The button in the world's actions and, once opened, its dialog. */
export function ShareWithTeam({
  client,
  worldId,
  worldName,
}: { client: ShareClient; worldId: string; worldName: string }) {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);
  return (
    <>
      <Button
        variant="secondary"
        onClick={(e) => {
          opener.current = e.currentTarget;
          setOpen(true);
        }}
      >
        Share with team
      </Button>
      {open ? (
        <ShareDialog
          client={client}
          worldId={worldId}
          worldName={worldName}
          onClose={() => {
            setOpen(false);
            opener.current?.focus();
          }}
        />
      ) : null}
    </>
  );
}
