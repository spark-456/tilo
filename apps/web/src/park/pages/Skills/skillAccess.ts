// FR-ACC-02 / BQ-DSN-04: a skill's level for a tool can only lower the team's level, never raise it. The same
// rule as tilo_policy.access_levels.effective_level (min of the two); skillAccess.test.ts compares this module
// with the shared fixture packages/policy/tests/fixtures/effective_level_pairs.json that the Python test also
// asserts. Pure view functions on sample data; no endpoint enforces a level yet.
import type { Learn, Skill } from "../../api/types";

export const LEVELS = ["Off", "Read", "Draft", "Act"] as const;
const TOP = LEVELS.length - 1;

const isLevel = (n: unknown): n is number =>
  Number.isInteger(n) && (n as number) >= 0 && (n as number) <= TOP;
/** A level kept inside the four; an unknown team level is clamped, never trusted. */
const clamp = (n: number): number =>
  Number.isFinite(n) ? Math.min(TOP, Math.max(0, Math.trunc(n))) : 0;

/** The level shown and used: min(team, skill). A missing, stale or tampered skill value is the team level. */
export function shownLevel(team: number, skill: number | undefined): number {
  const t = clamp(team);
  return isLevel(skill) ? Math.min(t, skill) : t;
}

/** The levels a picker offers for a team level: none above it. */
export const allowedLevels = (team: number): number[] =>
  LEVELS.map((_, i) => i).filter((i) => shownLevel(team, i) === i);

export interface ToolRow {
  skill: string;
  skillId: string;
  tool: string;
  team: number;
  level: number;
}

/** One row per skill tool whose team level is known (Learn.tools lists the team's tools as "Name · note"). */
export function toolRows(skills: Skill[], tools: Learn["tools"]): ToolRow[] {
  const team = new Map(tools.map((t) => [t[3].split(" · ")[0] ?? "", t[4]]));
  return skills.flatMap((s) =>
    s.tools.flatMap(([tool, level]) => {
      const t = team.get(tool);
      return t === undefined
        ? []
        : [{ skill: s.name, skillId: s.id, tool, team: clamp(t), level: shownLevel(t, level) }];
    }),
  );
}
