// FR-TEAM-01: the people directory from GET /v1/people, read only. UI-STUDIO-5 (design/studio-v2 "Tilo S Team"): a
// table of people with their role, teams, department and when they were last active. What each can say yes to and
// their backup are not in this read: the table says where limits live and that backups are not available yet.
import { ORGANISATION_SETUP } from "../../api/organisationSetup";
import type { Team } from "../../api/types";
import { initialsOf } from "./teamModel";

const NA = "Not available";

/** A read-only directory: the people endpoint does not provide activity, policy or write actions. */
export function LiveMembers({ team }: { team: Team }) {
  if (team.setupRequired) return <output>{ORGANISATION_SETUP}</output>;
  return (
    <section
      className="park-team-card park-team-members park-team-directory"
      aria-label="Members"
      data-testid="live-team"
    >
      {team.people.length === 0 ? (
        <p className="park-team-dirnote">No people returned.</p>
      ) : (
        <div className="park-team-scroll">
          <table className="park-team-dirtable">
            <thead>
              <tr className="park-team-dirhead">
                <th scope="col">Person</th>
                <th scope="col">Role</th>
                <th scope="col">Teams</th>
                <th scope="col">Department</th>
                <th scope="col">Active</th>
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
                        <span className="park-team-sub">{p.email ?? NA}</span>
                      </span>
                    </span>
                  </td>
                  <td className="park-team-strong">{p.role ?? NA}</td>
                  <td>{p.memberships == null ? NA : p.memberships.join(", ") || "None"}</td>
                  <td>{p.dept || NA}</td>
                  <td>{p.active || NA}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="park-team-dirnote">
        Roles, spend limits, invites and team rules are in Manage team settings. Backups for when
        someone is away and activity are not available yet.
      </p>
    </section>
  );
}
