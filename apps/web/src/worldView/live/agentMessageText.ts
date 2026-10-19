/** Turns a recorded handoff note into readable copy; an unrecognized payload is never shown as raw JSON. */
export function agentMessageText(text: string | null): string {
  if (!text?.trim()) return "Shared a work update.";
  try {
    const parsed: unknown = JSON.parse(text);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const record = parsed as Record<string, unknown>;
      for (const key of ["summary", "message", "text", "description"]) {
        const value = record[key];
        if (typeof value === "string" && value.trim()) return value.trim();
      }
      return "Shared a work update.";
    }
    if (typeof parsed === "string") return parsed.trim() || "Shared a work update.";
  } catch {
    /* Plain text is already readable. */
  }
  return text;
}
