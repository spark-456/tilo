// The reply of `POST /worlds/{id}/autopilot/stop` (services/api dispatch.py), and the check that a
// body has that shape before anything is shown as a result.

/** `POST /worlds/{id}/autopilot/stop`: 200, or 202 while `pending` changes are still being
 * recorded (services/api dispatch.py). */
export interface StopResult {
  readonly stopped: number;
  readonly already_l1: number;
  readonly confirmations: ReadonlyArray<{ readonly channel: string }>;
  readonly pending: number;
}

const count = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;

/** Whether a reply has the shape the API documents; anything else is not shown as a result. */
export const isStopResult = (v: unknown): v is StopResult => {
  const r = v as Partial<StopResult> | null;
  return (
    typeof r === "object" &&
    r !== null &&
    count(r.stopped) &&
    count(r.already_l1) &&
    count(r.pending) &&
    Array.isArray(r.confirmations) &&
    r.confirmations.every((c) => typeof c?.channel === "string")
  );
};
