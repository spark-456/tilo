// UI-STUDIO-2: "Make it a world" from a chat hands the question to Home's ask box, set to Make a world. The text is
// held in memory for the next Home mount only: never in the address (it is the person's own words) and never stored.
let pending: string | null = null;
let pendingSkill: import("../../api/skillRoute").CatalogSkill | null = null;

export function handDraft(
  text: string,
  skill: import("../../api/skillRoute").CatalogSkill | null = null,
): void {
  pending = text.trim() || (skill ? "" : null);
  pendingSkill = skill;
}

/** The handed-over question, once: the next caller gets null. */
export function takeDraft(): string | null {
  const text = pending;
  pending = null;
  return text;
}

export function takeDraftSkill(): import("../../api/skillRoute").CatalogSkill | null {
  const skill = pendingSkill;
  pendingSkill = null;
  return skill;
}
