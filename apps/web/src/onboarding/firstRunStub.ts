// FIRST-RUN: temporary seam explicitly approved in the 12 Oct 12:20 notice.
// Replace this import with the shared useFirstRun hook when its PR merges.
// Unknown preserves ONBOARD-1; never infer first-run from missing/failed data.
export function useFirstRun(): boolean | undefined {
  return undefined;
}
