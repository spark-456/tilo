// PRD 18.4 error rule, shared by the flow screens and the Park forms (moved out of screens/remote.ts, ADR-0035 L6d).
import { TiloApiError } from "./http";

export function describeError(doing: string, error: unknown): string {
  if (error instanceof TiloApiError && error.code === "intake_already_committed") {
    return error.message;
  }
  // PRD 18.4, say only what is known: a timeout, a dropped connection or a 5xx on a write may have
  // happened on the server, so "Nothing was changed" is not true and the person checks first.
  if (error instanceof TiloApiError && error.retryable && error.write) {
    return `Something went wrong while trying to ${doing}. We could not confirm it. Check before trying again.`;
  }
  const said = error instanceof Error && error.message ? error.message : "an unknown error";
  const reason = said.replace(/[.!?]+$/, ""); // the sentence below adds its own full stop
  return `Could not ${doing}: ${reason}. Nothing was changed. You can try again.`;
}
