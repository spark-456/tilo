import type { Team } from "../types";

const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0;

/** Read only the fields the directory actually supplies; absent fields are unknown, never samples. */
export function teamFromPeople(body: unknown): Team | null {
  if (!object(body) || !text(body.you) || !Array.isArray(body.people)) return null;
  const people: Team["people"] = [];
  for (const row of body.people) {
    if (!object(row) || !text(row.id) || !text(row.display_name)) return null;
    if (row.org_role !== undefined && row.org_role !== "owner" && row.org_role !== "member")
      return null;
    if (row.email !== undefined && !text(row.email)) return null;
    let memberships: string[] | null = null;
    if (row.memberships !== undefined) {
      if (!Array.isArray(row.memberships)) return null;
      memberships = [];
      for (const item of row.memberships) {
        if (!object(item) || !text(item.team)) return null;
        memberships.push(item.team);
      }
    }
    people.push({
      id: row.id,
      name: row.display_name,
      email: text(row.email) ? row.email : null,
      role: row.org_role === "owner" ? "Owner" : row.org_role === "member" ? "Member" : null,
      memberships,
      you: row.id === body.you,
      dept: null,
      active: null,
      c: null,
    });
  }
  // Other Team panels have no directory source. The live page shows their unavailability explicitly.
  return { people, rules: [], matrix: [], roles: [], coverage: [] };
}
