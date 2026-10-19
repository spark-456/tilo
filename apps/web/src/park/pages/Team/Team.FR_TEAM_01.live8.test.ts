// LIVE8-WEB-1 (FR-TEAM-01): the header count agrees in number, and the people table shows the signed-in person's own
// teams and lead role from the same data the "Your teams" panel reads.
import { describe, expect, it } from "vitest";
import type { Team } from "../../api/types";
import { peopleCount, withMyTeams } from "./teamModel";

const person = (id: string, you: boolean, role: "Member" | "Owner" = "Member") => ({
  id,
  name: id,
  email: null,
  role,
  memberships: [],
  you,
  dept: null,
  active: null,
  c: null,
});
const team = (role: "Member" | "Owner" = "Member"): Team => ({
  people: [person("u_me", true, role), person("u_o", false)],
  rules: [],
  matrix: [],
  roles: [],
  coverage: [],
});

describe("FR_TEAM_01 LIVE8 Team page", () => {
  it("FR_TEAM_01 says 1 person and N people", () => {
    expect(peopleCount(1)).toBe("1 person");
    expect(peopleCount(0)).toBe("0 people");
    expect(peopleCount(6)).toBe("6 people");
  });

  it("FR_TEAM_01 the table's own row takes team names and the lead role from Your teams", () => {
    const out = withMyTeams(team(), "u_me", [{ name: "Me's team", lead: true }]);
    const me = out.people.find((p) => p.id === "u_me");
    expect(me?.memberships).toEqual(["Me's team"]);
    expect(me?.role).toBe("Team lead");
    expect(out.people.find((p) => p.id === "u_o")?.memberships).toEqual([]);
  });

  it("FR_TEAM_01 an owner stays Owner, a plain member stays Member, no teams changes nothing", () => {
    expect(withMyTeams(team("Owner"), "u_me", [{ name: "A", lead: true }]).people[0]?.role).toBe(
      "Owner",
    );
    expect(withMyTeams(team(), "u_me", [{ name: "A", lead: false }]).people[0]?.role).toBe(
      "Member",
    );
    expect(withMyTeams(team(), "u_me", [])).toEqual(team());
  });
});
