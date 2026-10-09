// FR-MTG-09 (web side): who can host a meeting, which client can ask, and what each refusal of
// `POST /v1/meetings/{id}/host` says in plain words (services/api/tests/API_MTG09_b.md). The server's
// own text is never shown: a refusal is read by its status and its short word (`rule` or `detail`).
import type { Meeting } from "@tilo/contracts";
import type { TiloClient } from "../api/client";
import { TiloApiError } from "../api/http";
import type { HostStarted } from "../api/meetingHost";

/** A client that can ask for hosting. `hostMeeting` is on HttpClient only (not the frozen TiloClient
 * interface, not the fixture client), so it is detected here, like `pauseWorld`. */
export interface HostingClient extends TiloClient {
  hostMeeting(meetingId: string): Promise<HostStarted>;
}
export const canAskToHost = (client: TiloClient): client is HostingClient =>
  typeof (client as Partial<HostingClient>).hostMeeting === "function";

/** The owner of a meeting that is scheduled and joined by Tilo; for anyone else, or any other state,
 * the API answers 404 or 409, so no button is drawn. */
export const canHostMeeting = (m: Meeting, me: string): boolean =>
  m.owner === me && m.status === "scheduled" && m.source === "bot";

export const NOT_CONNECTED = "Hosting isn't connected yet. Nothing was started.";
const UNCONFIRMED =
  "We could not confirm whether hosting started. Check Needs you before trying again.";

const RULES: Readonly<Record<string, string>> = {
  "MH-01": "This meeting's record is not complete enough to host. Nothing was started.",
  "MH-02":
    "The meeting time cannot be hosted. It must be in the future and fit the hosting time limit. Nothing was started.",
  "MH-03":
    "Someone on the invite list cannot be invited. Every invitee must be a person of your organisation with an address. Nothing was started.",
  "MH-04":
    "Your time zone is not set, so Tilo cannot write the invitation time. Nothing was started.",
  "MH-06": "The invitation text is too long for the approval card. Nothing was started.",
};

/** One sentence per refusal, in the PRD 18.4 order: what happened, then what is true now. */
export function hostFailureText(error: unknown): string {
  if (!(error instanceof TiloApiError)) return "Hosting could not be started. Nothing was changed.";
  if (error.replayOnly) return error.message;
  const { status, refusal } = error;
  if (status === 404) return "That meeting was not found. Nothing was started.";
  if (status === 409) {
    if (refusal === "already_hosted") {
      return "Hosting was already requested for this meeting. Look in Needs you for its approval.";
    }
    return refusal === "not_hostable"
      ? "This meeting cannot be hosted. Only a scheduled meeting that Tilo joins can be."
      : "This meeting cannot be hosted right now. Nothing was started.";
  }
  if (status === 422) {
    return (
      RULES[refusal ?? ""] ?? "Tilo cannot host this meeting as it stands. Nothing was started."
    );
  }
  if (status === 403) return "You do not have access to host this meeting.";
  if (status === 401) return "You need to sign in to host this meeting.";
  if (status === 503) {
    return refusal === "not_configured"
      ? NOT_CONNECTED
      : "Tilo cannot start hosting right now. Nothing was started. Try again in a moment.";
  }
  if (status === null) return `Tilo could not be reached. ${UNCONFIRMED}`;
  if (error.retryable) return `${error.message.replace(/[.!?]+$/, "")}. ${UNCONFIRMED}`;
  return "Hosting could not be started. Nothing was changed.";
}
