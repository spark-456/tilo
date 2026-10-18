// FR-TEAM-01: the people directory from GET /v1/people, read only. UI-STUDIO-5 (design/studio-v2 "Tilo S Team"): a
// table of people with their role, teams, department and when they were last active. What each can say yes to and
// their backup are not in this read, so no column is drawn for them.
import { ORGANISATION_SETUP } from "../../api/organisationSetup";
import type { Team } from "../../api/types";
import { initialsOf } from "./teamModel";

const cleanMembership = (m: string): string => {
  if (m.startsWith("tm_")) {
    const raw = m.slice(3).replace(/[_-]/g, " ").trim();
    return raw.charAt(0).toUpperCase() + raw.slice(1);
  }
  return m;
};

/** A read-only directory: the people endpoint does not provide activity, policy or write actions. */
export function LiveMembers({ team }: { team: Team }) {
  const ownName = team.people.find((person) => person.you)?.name;
  const role = team.people.some((p) => !!p.role);
  const teams = team.people.some((p) => p.memberships !== null && p.memberships !== undefined);
  const department = team.people.some((p) => !!p.dept);
  const active = team.people.some((p) => !!p.active);
  return (
    <section
      className="park-team-card park-team-members park-team-directory"
      aria-label="Members"
      data-testid="live-team"
    >
      <div className="park-team-scroll">
        <table className="park-team-dirtable">
          <thead>
            <tr className="park-team-dirhead">
              <th scope="col">Person</th>
              {role ? <th scope="col">Role</th> : null}
              {teams ? <th scope="col">Teams</th> : null}
              {department ? <th scope="col">Department</th> : null}
              {active ? <th scope="col">Active</th> : null}
            </tr>
          </thead>
          <tbody>
            {team.people.map((p) => (
              <tr className="park-team-dirrow" key={p.id}>
                <td>
                  <span className="park-team-dirwho">
                    <span className="park-team-avatar" aria-hidden="true">
                      {initialsOf(p.name).slice(0, 2).toUpperCase()}
                    </span>
                    <span className="park-team-id">
                      <span className="park-team-name">
                        <span>{p.name === p.id ? (p.you ? "You" : "Team member") : p.name}</span>
                        {p.you ? (
                          <span className="park-team-tag park-team-tag--you">You</span>
                        ) : null}
                      </span>
                      {p.email ? <span className="park-team-sub">{p.email}</span> : null}
                    </span>
                  </span>
                </td>
                {role ? <td className="park-team-strong">{p.role}</td> : null}
                {teams ? <td>{p.memberships?.map(cleanMembership).join(", ")}</td> : null}
                {department ? <td>{p.dept}</td> : null}
                {active ? <td>{p.active}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!team.people.length ? <p className="park-team-dirnote">{ORGANISATION_SETUP}</p> : null}
      <div className="park-team-two">
        <article className="park-team-card park-team-empty" aria-label="Your member card">
          <h3 className="park-team-h2">
            {ownName && ownName !== team.people.find((p) => p.you)?.id ? ownName : "Your card"}
          </h3>
          <p className="park-team-dirnote">
            {ownName
              ? "You are on this team."
              : "Your details appear here when your team is connected."}
          </p>
        </article>
        <article className="park-team-card park-team-empty" aria-label="Invite a teammate">
          <h3 className="park-team-h2">Invite a teammate</h3>
          <p className="park-team-dirnote">Invite by email from Your teams above.</p>
        </article>
        <article className="park-team-card park-team-empty" aria-label="Shared worlds">
          <h3 className="park-team-h2">Shared worlds</h3>
          <p className="park-team-dirnote">Shared worlds appear here when this team has them.</p>
        </article>
      </div>
    </section>
  );
}
