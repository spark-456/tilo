import type { Skill } from "../../api/types";
import type { RunEvent } from "./useRunEvents";

const skillIdOf = (event: RunEvent): string | null => {
  if (!event.data || typeof event.data !== "object") return null;
  const id = (event.data as { skill?: unknown }).skill;
  return typeof id === "string" ? id : null;
};

export function skillNameForEvent(event: RunEvent, skills: readonly Skill[]): string | null {
  if (event.type !== "skill.loaded") return null;
  const id = skillIdOf(event);
  const name = skills.find((skill) => skill.id === id)?.name.trim();
  return name || null;
}

export function loadedSkillNames(
  events: readonly RunEvent[],
  skills: readonly Skill[],
): readonly string[] {
  return [
    ...new Set(events.map((event) => skillNameForEvent(event, skills)).filter(Boolean)),
  ] as string[];
}

export function storySummary(event: RunEvent, skills: readonly Skill[]): string {
  if (event.type !== "skill.loaded") return event.summary;
  const name = skillNameForEvent(event, skills);
  return name
    ? `The team loaded the skill ${name}.`
    : "The team loaded a skill.";
}
