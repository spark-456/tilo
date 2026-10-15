// SELF-SERVE-TEAMS (ADR-0044, PE-37): the signed-in person's own teams. Create a team (you lead it), invite people
// to a team you lead by email, accept or decline an invitation, leave a team. Every list is re-read from the server
// after a write; nothing is shown as done until the server answered. Renders nothing without a live client.
import { useCallback, useEffect, useState } from "react";
import {
  type MyTeam,
  type RosterMember,
  type TeamsClient,
  teamsClient,
} from "../../api/selfServeTeams";
import { Button } from "../../components";
import { type MyTeamName, isValidEmail } from "./teamModel";

export const INVITE_SENT =
  "Invitation saved. If that address belongs to someone who has signed in, they will see it on their Team page.";

interface Loaded {
  teams: MyTeam[];
  you: string | null;
  rosters: Record<string, RosterMember[]>;
}

async function load(client: TeamsClient): Promise<Loaded> {
  const { teams, you } = await client.mine();
  const rosters: Record<string, RosterMember[]> = {};
  for (const t of teams) {
    if (t.state === "member") rosters[t.team] = await client.roster(t.team).catch(() => []);
  }
  return { teams, you, rosters };
}

function teamName(roster: RosterMember[] | undefined): string {
  const lead = roster?.find((m) => m.lead);
  return lead ? `${lead.name}'s team` : "Team";
}

function Invite({
  onInvite,
  busy,
}: { onInvite: (email: string) => Promise<boolean>; busy: boolean }) {
  const [email, setEmail] = useState("");
  const valid = isValidEmail(email);
  const send = () => {
    if (!valid || busy) return;
    void onInvite(email.trim()).then((ok) => ok && setEmail(""));
  };
  return (
    <div className="park-team-invite">
      <div className="park-team-field">
        <input
          className="park-team-input"
          aria-label="Invite to your team by email"
          placeholder="name@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
      </div>
      <Button variant="secondary" disabled={!valid || busy} onClick={send}>
        Invite
      </Button>
    </div>
  );
}

export function SelfServeTeams(props: {
  client?: TeamsClient | null;
  /** The person's own teams after every read, for the people table beside this panel. */
  onLoaded?: (you: string | null, teams: MyTeamName[]) => void;
}) {
  const { onLoaded } = props;
  const [client] = useState(() => (props.client === undefined ? teamsClient() : props.client));
  const [data, setData] = useState<Loaded | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!client) return;
    try {
      const next = await load(client);
      setData(next);
      onLoaded?.(
        next.you,
        next.teams.flatMap((t) =>
          t.state === "member" ? [{ name: teamName(next.rosters[t.team]), lead: t.lead }] : [],
        ),
      );
    } catch {
      setData(null);
    }
  }, [client, onLoaded]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!client || !data) return null;

  const act = async (work: () => Promise<void>, done: string): Promise<boolean> => {
    setBusy(true);
    try {
      await work();
      setNote(done);
      await refresh();
      return true;
    } catch {
      setNote("That did not go through. Nothing was changed.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="park-team-card" aria-label="Your teams" data-testid="self-serve-teams">
      <h2 className="park-team-h2">Your teams</h2>
      {data.teams.length === 0 ? <p>You are not in a team yet.</p> : null}
      {data.teams.map((t) =>
        t.state === "lapsed" ? (
          <div className="park-team-details" key={t.team} data-testid="team-lapsed">
            <p>An invitation that no longer counts. Remove it to free the place.</p>
            {data.you ? (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  void act(() => client.leave(t.team, data.you ?? ""), "Old invitation removed.")
                }
              >
                Remove
              </Button>
            ) : null}
          </div>
        ) : t.state === "pending" ? (
          <div className="park-team-details" key={t.team} data-testid="team-invitation">
            <p>{`${t.invitedBy ?? "A team lead"} invited you to their team.`}</p>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void act(() => client.accept(t.team), "You joined the team.")}
            >
              Accept
            </Button>
            {data.you ? (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  void act(() => client.leave(t.team, data.you ?? ""), "Invitation declined.")
                }
              >
                Decline
              </Button>
            ) : null}
          </div>
        ) : (
          <div className="park-team-details" key={t.team} data-testid="team-row">
            <h3 className="park-team-h2">
              {teamName(data.rosters[t.team])}
              {t.lead ? " · You lead it" : ""}
            </h3>
            <ul>
              {(data.rosters[t.team] ?? []).map((m) => (
                <li key={m.id}>
                  {m.name}
                  {m.lead ? " (lead)" : ""}
                </li>
              ))}
            </ul>
            {t.lead ? (
              <Invite
                busy={busy}
                onInvite={(email) => act(() => client.invite(t.team, email), INVITE_SENT)}
              />
            ) : null}
          </div>
        ),
      )}
      <Button
        variant="secondary"
        disabled={busy}
        onClick={() => void act(() => client.create(), "Team created. You lead it.")}
      >
        Create a team
      </Button>
      <output>{note}</output>
    </section>
  );
}
