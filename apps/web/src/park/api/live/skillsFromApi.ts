// SKILLS-3 (FR-SKL-04): the taught-skill records of GET /v1/skills as the Park `Skill`, and the teach card's draft as
// the body of POST /v1/skills. Nothing is invented: the server serves no runs, success rate, last run or
// improvement yet, so those read as 0, null and "" (the page prints "—" or the empty text). A row that does not
// match the shape is left out, never repaired.
import type { Skill, SkillDraft } from "../types";

interface Step {
  text: string;
  tool: string;
  action: string;
  ask_first: boolean;
}
interface Question {
  text: string;
  options: string[];
  answer: unknown;
}
export interface SkillRow {
  id: string;
  name: string;
  scope: { kind: "just_me" | "team"; team: string | null };
  status: "draft" | "learning" | "trusted";
  paused: boolean;
  plan: Step[];
  question: Question | null;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const isText = (v: unknown): v is string => typeof v === "string";

const isStep = (v: unknown): v is Step =>
  isObject(v) &&
  isText(v.text) &&
  isText(v.tool) &&
  isText(v.action) &&
  typeof v.ask_first === "boolean";

const isQuestion = (v: unknown): v is Question =>
  isObject(v) && isText(v.text) && Array.isArray(v.options) && v.options.every(isText);

export function isSkillRow(v: unknown): v is SkillRow {
  if (!isObject(v) || !isText(v.id) || !isText(v.name) || typeof v.paused !== "boolean")
    return false;
  const scope = v.scope;
  return (
    isObject(scope) &&
    (scope.kind === "just_me" || scope.kind === "team") &&
    (scope.team === null || isText(scope.team)) &&
    (v.status === "draft" || v.status === "learning" || v.status === "trusted") &&
    Array.isArray(v.plan) &&
    v.plan.every(isStep) &&
    (v.question === null || isQuestion(v.question))
  );
}

/** The tool chips: one per tool, at the most generous level any of its steps needs (Read 1, ask first 2, Act 3). */
function toolsOf(plan: Step[]): [string, number][] {
  const levels = new Map<string, number>();
  for (const s of plan) {
    const level = s.ask_first ? 2 : s.action.startsWith("read") ? 1 : 3;
    levels.set(s.tool, Math.max(levels.get(s.tool) ?? 0, level));
  }
  return [...levels];
}

export function skillFromRow(r: SkillRow): Skill {
  const ask =
    r.question && r.question.answer == null
      ? { ask: { q: r.question.text, a: [...r.question.options] } }
      : {};
  return {
    id: r.id,
    name: r.name,
    team: r.scope.team ?? "",
    owner: r.scope.kind === "just_me" ? "You" : "",
    role: "",
    runs: 0,
    rate: null,
    last: "",
    improved: "",
    status: r.status === "draft" ? "draft" : "live",
    st: r.status === "draft" ? "draft" : r.paused ? "review" : r.status,
    from: "",
    tools: toolsOf(r.plan),
    used: [],
    steps: r.plan.map((s) => s.text),
    ...ask,
  };
}

/** `skills` rows of the answer that match the shape; null when the body is not a skill list at all. */
export function skillsOfBody(v: unknown): Skill[] | null {
  if (!isObject(v) || !Array.isArray(v.skills)) return null;
  return v.skills.filter(isSkillRow).map(skillFromRow);
}

/** A body that is a Learn answer (`learning` rows, `needs_rating`) the page can read. */
export const isLearnBody = (v: unknown): boolean =>
  isObject(v) && Array.isArray(v.learning) && Array.isArray(v.needs_rating);

// The labels the teach card prints beside a step, as the connector action the server knows. Any other label is sent
// as written and the server refuses it (unknown_action): the page then says it could not save.
const KNOWN: Record<string, [string, string]> = {
  "Gmail · Read": ["gmail", "read_email"],
  "Files · Read": ["google_drive", "read_file"],
};

const slug = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, "_");

/** The POST body for a draft, or null when the draft is something the server cannot take yet (a team without an
 * id, a timed trigger without a schedule): the caller refuses without a request. */
export function saveBody(name: string, d: SkillDraft): Record<string, unknown> | null {
  if (d.scope !== "me" || d.trigger !== "ask" || d.plan.length === 0) return null;
  return {
    name,
    scope: { kind: "just_me", team: null },
    trigger: { kind: "on_demand" },
    plan_steps: d.plan.map((p) => {
      const [label = "", level = ""] = p.tool.split(" · ");
      const [tool, action] = KNOWN[p.tool] ?? [slug(label), slug(level)];
      const verb = level === "Read" ? "read" : "write";
      return { text: p.text, tool, action, verb, ask_first: p.ask };
    }),
  };
}
