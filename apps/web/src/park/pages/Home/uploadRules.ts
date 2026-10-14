// FR-INT-01 upload limits the composer checks before Start. A Park page may not import the legacy screens, so
// these are ported from the retired S-01 intakeRules (the server's own: packages/planning intake `_check_limits`).
export const MAX_FILES = 10;
export const MAX_BYTES = 50 * 1024 * 1024;
export const ACCEPTED = "PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG";
export const ACCEPT_ATTR = ".pdf,.docx,.pptx,.xlsx,.csv,.png,.jpg,.jpeg";

const EXTENSIONS = new Set(ACCEPT_ATTR.split(","));

export function isAccepted(name: string): boolean {
  const dot = name.lastIndexOf(".");
  return dot > 0 && EXTENSIONS.has(name.slice(dot).toLowerCase());
}

/** FR-INT-01: the longest task text the intake takes, counted in code points as the server does. */
export const MAX_TEXT = 4000;
export const codePoints = (text: string): number => Array.from(text).length;
/** The server's own sentence for a text over the limit (packages/planning intake `_check_limits`), or null. */
export const textLimitMessage = (text: string): string | null => {
  const length = codePoints(text);
  return length > MAX_TEXT ? `The text is ${length} characters; the limit is ${MAX_TEXT}.` : null;
};
