import type { Team } from "../../api/types";

/** A read-only directory: the people endpoint does not provide activity, policy or write actions. */
export function LiveMembers({ team }: { team: Team }) {
  return (
    <section
      className="park-team-card park-team-members"
      aria-label="Members"
      data-testid="live-team"
    >
      {team.people.length === 0 ? (
        <p>No people returned.</p>
      ) : (
        team.people.map((p) => (
          <div className="park-team-details" key={p.id}>
            <h2 className="park-team-h2">
              {p.name}
              {p.you ? " · You" : ""}
            </h2>
            <dl>
              {(
                [
                  ["Email", p.email],
                  ["Department", p.dept],
                  ["Role", p.role],
                  [
                    "Memberships",
                    p.memberships == null ? null : p.memberships.join(", ") || "None",
                  ],
                  ["Active", p.active],
                  ["Colour", p.c],
                ] as const
              ).map(([label, value]) => (
                <div className="park-team-fact" key={label}>
                  <dt className="park-team-fact-k">{label}</dt>
                  <dd className="park-team-fact-v">{value ?? "Not available"}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))
      )}
      <p>
        Invites, role changes, spend limits, activity, coverage and team rules are not available
        yet.
      </p>
    </section>
  );
}
