import type { Skill } from "../../api/types";

export type SkillIconKind =
  | "mail"
  | "research"
  | "calendar"
  | "table"
  | "globe"
  | "writing"
  | "meeting"
  | "code"
  | "default";

const RULES: readonly [SkillIconKind, RegExp][] = [
  ["mail", /\b(mail|email|gmail|inbox)\b/],
  ["meeting", /\b(meet|meeting|meetings|attendee|attendees|people)\b/],
  ["calendar", /\b(calendar|schedule|scheduling|event|events)\b/],
  ["table", /\b(spreadsheet|sheet|sheets|table|csv|excel|invoice|invoices|finance)\b/],
  ["globe", /\b(browser|browse|web|site|website|websites)\b/],
  ["research", /\b(research|search|source|sources|investigate)\b/],
  ["writing", /\b(write|writing|writer|draft|brief|document)\b/],
  ["code", /\b(code|coding|program|script|developer)\b/],
];

/** Pure display choice from served fields: what the skill does outranks its connectors. */
export function skillIconKind(skill: Pick<Skill, "name" | "tools" | "role">): SkillIconKind {
  const toolWords = skill.tools
    .map(([tool]) => tool.replace(/[_-]/g, " "))
    .join(" ")
    .toLowerCase();
  for (const words of [skill.name.toLowerCase(), skill.role.toLowerCase(), toolWords]) {
    for (const [kind, pattern] of RULES) if (pattern.test(words)) return kind;
  }
  return "default";
}

const ICONS: Record<SkillIconKind, string> = {
  mail: "envelope",
  research: "magnifying-glass",
  calendar: "calendar",
  table: "bar-chart",
  globe: "globe",
  writing: "memo",
  meeting: "people",
  code: "laptop",
  default: "clipboard",
};

export function SkillIcon({ skill }: { skill: Pick<Skill, "name" | "tools" | "role"> }) {
  return (
    <img
      src={`/park/skills/${ICONS[skillIconKind(skill)]}.svg`}
      alt={`${skill.name} icon`}
      width="25"
      height="25"
      loading="lazy"
      decoding="async"
    />
  );
}
