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

// P0-SKILLS-TEACH: "teach Tilo to ..." typed on Home opens the Teach wizard on Skills with the words already in it.
let pendingTeach: string | null = null;

export function handTeach(text: string): void {
  pendingTeach = text.trim() || null;
}

/** The handed-over description, once: the next caller gets null. */
export function takeTeach(): string | null {
  const text = pendingTeach;
  pendingTeach = null;
  return text;
}

/** "Teach Tilo to: every Monday ..." -> the words after it; null for any other text (a plain task). */
export function teachIntent(query: string): string | null {
  const m = /^\s*(?:please\s+)?teach\s+tilo\s*(?:to|how\s+to|that)?\s*[:,\-–—]?\s*([\s\S]+)$/i.exec(
    query,
  );
  const words = m?.[1]?.trim() ?? "";
  return words.length >= 3 ? words : null;
}
