// FR-INT-01 upload limits the composer checks before Start. A Park page may not import the legacy screens, so
// these mirror apps/web/src/screens/flow/intakeRules.ts (the server's own: packages/planning intake `_check_limits`).
export const MAX_FILES = 10;
export const MAX_BYTES = 50 * 1024 * 1024;
export const ACCEPTED = "PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG";
export const ACCEPT_ATTR = ".pdf,.docx,.pptx,.xlsx,.csv,.png,.jpg,.jpeg";

const EXTENSIONS = new Set(ACCEPT_ATTR.split(","));

export function isAccepted(name: string): boolean {
  const dot = name.lastIndexOf(".");
  return dot > 0 && EXTENSIONS.has(name.slice(dot).toLowerCase());
}
