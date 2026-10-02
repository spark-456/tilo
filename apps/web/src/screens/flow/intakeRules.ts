// FR-INT-01 limits, checked before submit with the server's own wording
// (packages/planning/src/tilo_planning/intake.py `_check_limits`, same order and same messages).
export const MAX_TEXT = 4000;
export const MAX_FILES = 10;
export const MAX_BYTES = 50 * 1024 * 1024;
export const ACCEPTED = "PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG";
export const ACCEPT_ATTR = ".pdf,.docx,.pptx,.xlsx,.csv,.png,.jpg,.jpeg";

export interface FileInfo {
  readonly name: string;
  readonly size: number;
}

const EXTENSIONS = new Set(ACCEPT_ATTR.split(","));
const clip = (s: string, n: number) => (s.length <= n ? s : `${s.slice(0, n - 1)}…`);

export function isAccepted(name: string): boolean {
  const dot = name.lastIndexOf(".");
  return dot > 0 && EXTENSIONS.has(name.slice(dot).toLowerCase());
}

export const checkLength = (length: number): string | null =>
  length > MAX_TEXT ? `The text is ${length} characters; the limit is ${MAX_TEXT}.` : null;

export function checkFiles(files: readonly FileInfo[]): string | null {
  if (files.length > MAX_FILES) return `${files.length} files attached; the limit is ${MAX_FILES}.`;
  if (files.reduce((sum, f) => sum + f.size, 0) > MAX_BYTES) {
    return `The files total more than ${MAX_BYTES / (1024 * 1024)} MB.`;
  }
  const bad = files.find((f) => !isAccepted(f.name));
  return bad
    ? `${clip(bad.name || "A file", 80)} is not accepted; attach ${ACCEPTED} files.`
    : null;
}

/** The first problem the server would report for this task, or null. */
export function checkIntake(text: string, files: readonly FileInfo[]): string | null {
  if (!text.trim()) return "Describe the task in text.";
  return checkLength(text.length) ?? checkFiles(files);
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
