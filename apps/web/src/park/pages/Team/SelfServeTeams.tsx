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
const MEMBER_ROLES = ["viewer", "editor", "admin"] as const;

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

function teamName(team: MyTeam, roster: RosterMember[] | undefined): string {
  if (team.name) return team.name;
  const lead = roster?.find((m) => m.lead);
  return lead ? `Team led by ${lead.name}` : "Team";
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
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const refresh = useCallback(async () => {
    if (!client) return;
    try {
      const next = await load(client);
      setData(next);
      onLoaded?.(
        next.you,
        next.teams.flatMap((t) =>
          t.state === "member" ? [{ name: teamName(t, next.rosters[t.team]), lead: t.lead }] : [],
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
    <section
      className="park-team-card park-team-own"
      aria-label="Your teams"
      data-testid="self-serve-teams"
    >
      <div className="park-team-ownhead">
        <div>
          <h2 className="park-team-h2">Your teams</h2>
          <p className="park-team-ownhint">Create spaces for the people and work you share.</p>
        </div>
        {!creating ? (
          <Button variant="secondary" disabled={busy} onClick={() => setCreating(true)}>
            Create a team
          </Button>
        ) : null}
      </div>
      {creating ? (
        <div className="park-team-create">
          <label className="park-team-createlabel" htmlFor="park-team-name">
            Team name
          </label>
          <div className="park-team-createactions">
            <input
              id="park-team-name"
              className="park-team-input"
              aria-label="Team name"
              maxLength={80}
              placeholder="e.g. Launch crew"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setCreating(false);
                  setName("");
                }
              }}
            />
            <Button
              variant="primary"
              disabled={busy || !name.trim()}
              onClick={() =>
                void act(() => client.create(name.trim()), "Team created. You lead it.").then(
                  (ok) => {
                    if (ok) {
                      setCreating(false);
                      setName("");
                    }
                  },
                )
              }
            >
              {`Create ${name.trim() || "team"}`}
            </Button>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => {
                setCreating(false);
                setName("");
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
      {data.teams.length === 0 ? (
        <div className="park-team-ownempty">
          <span className="park-team-ownmark" aria-hidden="true">
            +
          </span>
          <p>You are not in a team yet.</p>
          <span>Name a team to start sharing worlds and inviting people.</span>
        </div>
      ) : null}
      <div className="park-team-ownlist">
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
            <article className="park-team-ownrow" key={t.team} data-testid="team-row">
              <div className="park-team-ownrowhead">
                <span className="park-team-ownavatar" aria-hidden="true">
                  {teamName(t, data.rosters[t.team]).slice(0, 1).toUpperCase()}
                </span>
                <div>
                  <h3 className="park-team-h2">
                    {teamName(t, data.rosters[t.team])}
                    {t.lead ? " · You lead it" : ""}
                  </h3>
                  <span>{`${data.rosters[t.team]?.length ?? 0} ${(data.rosters[t.team]?.length ?? 0) === 1 ? "person" : "people"}`}</span>
                </div>
              </div>
              <ul className="park-team-ownpeople">
                {(data.rosters[t.team] ?? []).map((m) => (
                  <li className="park-team-ownperson" key={m.id}>
                    <span>
                      {m.name}
                      {m.lead ? " · Owner" : ""}
                    </span>
                    {t.lead && !m.lead ? (
                      <span className="park-team-selectwrap">
                        <select
                          className="park-team-select"
                          aria-label={`Role for ${m.name}`}
                          value={m.role ?? "viewer"}
                          disabled={busy}
                          onChange={(e) => {
                            const role = e.target.value as (typeof MEMBER_ROLES)[number];
                            void act(
                              () => client.changeRole(t.team, m.id, role),
                              `${m.name} is now ${role[0]?.toUpperCase()}${role.slice(1)}.`,
                            );
                          }}
                        >
                          {MEMBER_ROLES.map((role) => (
                            <option key={role} value={role}>
                              {`${role[0]?.toUpperCase()}${role.slice(1)}`}
                            </option>
                          ))}
                        </select>
                      </span>
                    ) : (
                      !m.lead && (
                        <span>{`${(m.role ?? "viewer")[0]?.toUpperCase()}${(m.role ?? "viewer").slice(1)}`}</span>
                      )
                    )}
                  </li>
                ))}
              </ul>
              {t.lead ? (
                <Invite
                  busy={busy}
                  onInvite={(email) => act(() => client.invite(t.team, email), INVITE_SENT)}
                />
              ) : null}
            </article>
          ),
        )}
      </div>
      <output className="park-team-ownnote">{note}</output>
    </section>
  );
}
