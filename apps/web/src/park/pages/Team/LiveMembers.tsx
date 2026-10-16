// FR-TEAM-01: the people directory from GET /v1/people, read only. UI-STUDIO-5 (design/studio-v2 "Tilo S Team"): a
// table of people with their role, teams, department and when they were last active. What each can say yes to and
// their backup are not in this read, so no column is drawn for them.
import { ORGANISATION_SETUP } from "../../api/organisationSetup";
import type { Team } from "../../api/types";
import { initialsOf } from "./teamModel";

/** A read-only directory: the people endpoint does not provide activity, policy or write actions. */
export function LiveMembers({ team }: { team: Team }) {
  if (team.setupRequired) return <output>{ORGANISATION_SETUP}</output>;
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
      {team.people.length === 0 ? (
        <p className="park-team-dirnote">Create a team above, then invite people by email.</p>
      ) : (
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
                          <span>{p.name}</span>
                          {p.you ? (
                            <span className="park-team-tag park-team-tag--you">You</span>
                          ) : null}
                        </span>
                        {p.email ? <span className="park-team-sub">{p.email}</span> : null}
                      </span>
                    </span>
                  </td>
                  {role ? <td className="park-team-strong">{p.role}</td> : null}
                  {teams ? <td>{p.memberships?.join(", ")}</td> : null}
                  {department ? <td>{p.dept}</td> : null}
                  {active ? <td>{p.active}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {team.people.length ? (
        <p className="park-team-dirnote">
          Invite people by email in Your teams above. Owners can manage roles in Manage team
          settings.
        </p>
      ) : null}
    </section>
  );
}
