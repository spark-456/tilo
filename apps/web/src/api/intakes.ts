// The intake results made in this session, keyed by task id. S-01 (legacy start screen) and the Park Home
// composer (FR-UX-13) put them here; S-02 reads the brief from it, because the client has no "get intake" call.
// Lives under src/api so the Park live Api can write it without importing a screen.
import type { IntakeResult } from "./client";

export const intakes = new Map<string, IntakeResult>();
export const rememberIntake = (i: IntakeResult): void => void intakes.set(i.task_id, i);
