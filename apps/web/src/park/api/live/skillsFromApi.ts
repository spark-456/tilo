// SKILLS-3 (FR-SKL-04): the taught-skill records of GET /v1/skills as the Park `Skill`, and the teach card's draft as
// the body of POST /v1/skills. Nothing is invented: the server serves no runs, success rate, last run or
// improvement yet, so those read as 0, null and "" (the page prints "—" or the empty text). A row that does not
// match the shape is left out, never repaired.
import type { Skill, SkillCapture, SkillDraft, SkillVersion } from "../types";

interface Step {
  text: string;
  tool: string;
  action: string;
  ask_first: boolean;
  must_ask?: boolean;
}
interface Question {
  text: string;
  options: string[];
  answer: unknown;
}
export interface SkillRow {
  version?: number;
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
    runs: null,
    rate: null,
    last: "",
    improved: "",
    status: r.status === "draft" ? "draft" : "live",
    st: r.status === "draft" ? "draft" : r.paused ? "review" : r.status,
    from: "",
    tools: toolsOf(r.plan),
    used: [],
    steps: r.plan.map((s) => s.text),
    ...(Number.isInteger(r.version) && (r.version ?? 0) > 0
      ? {
          fix: {
            version: r.version as number,
            asks: r.plan.map((s) => s.ask_first),
            locked: r.plan.map((s) => s.must_ask !== false),
          },
        }
      : {}),
    ...ask,
    ...(r.paused ? { paused: true } : {}),
  };
}

/** `skills` rows of the answer that match the shape; null when the body is not a skill list at all. */
export function skillsOfBody(v: unknown): Skill[] | null {
  if (!isObject(v) || !Array.isArray(v.skills)) return null;
  const builtins: Skill[] = [];
  for (const r of Array.isArray(v.builtins) ? v.builtins : []) {
    if (!isObject(r) || !isText(r.id) || !isText(r.description) || !isText(r.version)) continue;
    builtins.push({
      id: r.id,
      name: r.id
        .split("-")
        .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
        .join(" "),
      builtin: true,
      description: r.description,
      owner: "Tilo",
      team: "",
      role: "",
      runs: null,
      rate: null,
      last: "",
      improved: "",
      status: "live",
      st: "draft",
      from: r.version,
      tools: [],
      used: [],
      steps: [],
    });
  }
  return [...builtins, ...v.skills.filter(isSkillRow).map(skillFromRow)];
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
  const { server } = d;
  if (server) {
    // A taught version goes back as the server made it (SKILLS-5); only the person's "ask first" choices differ.
    return {
      name,
      scope: { kind: "just_me", team: null },
      trigger: { kind: "on_demand" },
      plan_steps: server.steps.map((s) => ({
        text: s.text,
        tool: s.tool,
        action: s.action,
        verb: s.verb,
        ask_first: s.ask,
      })),
      captured_steps: server.captured.map((text) => ({ text })),
      ...(server.question ? { clarifying_question: server.question } : {}),
    };
  }
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

/** The answer of `POST /v1/skills/captures`: the draft's id and the steps it read, or null when unreadable. */
export function captureOfBody(v: unknown): SkillCapture | null {
  if (!isObject(v) || !isText(v.capture_id) || v.capture_id === "") return null;
  const steps = v.captured_steps;
  if (!Array.isArray(steps) || steps.length === 0) return null;
  if (!steps.every((s) => isObject(s) && isText(s.text))) return null;
  return { id: v.capture_id, steps: steps.map((s) => (s as { text: string }).text) };
}

const isCount = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0;

/** The answer of `POST /v1/skills/captures/{id}/version`; estimates the page cannot read are null, never guessed. */
export function versionOfBody(v: unknown): SkillVersion | null {
  if (!isObject(v) || !Array.isArray(v.plan_steps) || v.plan_steps.length === 0) return null;
  const steps: SkillVersion["steps"] = [];
  for (const s of v.plan_steps) {
    const raw = s as Record<string, unknown>;
    if (!isStep(s) || !isText(raw.verb) || typeof raw.must_ask !== "boolean") return null;
    steps.push({
      text: s.text,
      tool: s.tool,
      action: s.action,
      verb: raw.verb,
      ask: s.ask_first,
      locked: raw.must_ask,
    });
  }
  const q = v.clarifying_question ?? null;
  if (q !== null && !isQuestion(q)) return null;
  const e = v.estimates;
  const estimates =
    isObject(e) &&
    isCount(e.credits_per_run) &&
    isCount(e.seconds_per_run) &&
    isCount(e.asks_per_run)
      ? { credits: e.credits_per_run, seconds: e.seconds_per_run, asks: e.asks_per_run }
      : null;
  return {
    steps,
    question: q === null ? null : { text: q.text, options: [...q.options] },
    estimates,
  };
}
