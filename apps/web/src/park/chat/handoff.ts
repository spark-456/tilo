// UI-STUDIO-2: "Make it a world" from a chat hands the question to Home's ask box, set to Make a world. The text is
// held in memory for the next Home mount only: never in the address (it is the person's own words) and never stored.
let pending: string | null = null;

export function handDraft(text: string): void {
  pending = text.trim() || null;
}

/** The handed-over question, once: the next caller gets null. */
export function takeDraft(): string | null {
  const text = pending;
  pending = null;
  return text;
}
