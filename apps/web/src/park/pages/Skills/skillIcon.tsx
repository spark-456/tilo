import {
  BookOpen,
  Braces,
  CalendarDays,
  Globe2,
  type LucideIcon,
  Mail,
  PenLine,
  Shapes,
  Table2,
  UsersRound,
} from "lucide-react";
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

const ICONS: Record<SkillIconKind, LucideIcon> = {
  mail: Mail,
  research: BookOpen,
  calendar: CalendarDays,
  table: Table2,
  globe: Globe2,
  writing: PenLine,
  meeting: UsersRound,
  code: Braces,
  default: Shapes,
};

export function SkillIcon({ skill }: { skill: Pick<Skill, "name" | "tools" | "role"> }) {
  const Icon = ICONS[skillIconKind(skill)];
  return <Icon aria-hidden="true" focusable="false" size={25} strokeWidth={1.9} />;
}
