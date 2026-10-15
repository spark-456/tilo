// FR-MTG-01, FR-MTG-09, FR-MTG-10 (ADR-0024, ADR-0032): the Agenda's calls for a Tilo-hosted Google Meet.
// create -> world -> host is the owner's own request; `attend` is one long-held request that ends when the bot leaves.
// Nothing here retries, and nothing is "started" unless the API's reply said so. Request bodies follow
// `services/api people_writes.MeetingIn` (attest, notice_version, title, source, scheduled, attendees).
import { type HttpClient, TiloApiError } from "../../../api/http";
import { type HostForm, meetingBody } from "../../shared/hostMeetingRules";

const ID = /^mt_[A-Za-z0-9_]{1,48}$/;
const MEET = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/;
const bad = () => new TiloApiError("The meeting reply could not be read.", 200, false);
const isObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);

/** How a captured meeting ended, from the stored `ended_reason` (meeting.schema.json). */
export const ENDED_TEXT: Readonly<Record<string, string>> = {
  completed: "The meeting ended and Tilo left.",
  left_on_request: "Someone typed Tilo leave, so Tilo left.",
  removed: "Tilo was removed from the meeting.",
  timeout: "Tilo waited and was not admitted, or the call timed out, so it left.",
  failed: "Tilo could not stay in the meeting.",
};

export function meetingHostApi(http: Pick<HttpClient, "getJson" | "postJson" | "hostMeeting">) {
  const path = (id: string, action: string) => {
    if (!ID.test(id)) throw bad();
    return `/v1/meetings/${id}/${action}`;
  };
  return {
    /** Step 1. The key makes one tap one meeting even if the same request is sent twice. */
    async create(f: HostForm, key: string): Promise<string> {
      const reply = await http.postJson("/v1/meetings", meetingBody(f), { "Idempotency-Key": key });
      if (!isObject(reply) || typeof reply.id !== "string" || !ID.test(reply.id)) throw bad();
      return reply.id;
    },
    /** Step 2: the meeting's world, written once. */
    async world(id: string): Promise<void> {
      await http.postJson(path(id, "world"), {});
    },
    /** Step 3: the gate card "Exactly what will be sent" is raised in the reply's world. Nothing is sent yet. */
    async host(id: string): Promise<string> {
      path(id, "host");
      return (await http.hostMeeting(id)).world_id;
    },
    /** One request held open until the bot leaves (up to about 45 minutes). */
    async attend(id: string): Promise<{ status: string; reason: string | null }> {
      const r = await http.postJson(path(id, "attend"), {});
      if (!isObject(r) || r.id !== id || typeof r.status !== "string") throw bad();
      return {
        status: r.status,
        reason: typeof r.ended_reason === "string" ? r.ended_reason : null,
      };
    },
    /** Read on a click only (ADR-0024 amendment 4); the link is held in memory for `expires_at`. */
    async join(id: string): Promise<{ url: string; expires: number }> {
      const r = await http.getJson(path(id, "join"));
      if (!isObject(r) || typeof r.join_url !== "string" || !MEET.test(r.join_url)) throw bad();
      const expires = typeof r.expires_at === "string" ? Date.parse(r.expires_at) : Number.NaN;
      if (Number.isNaN(expires)) throw bad();
      return { url: r.join_url, expires };
    },
  };
}
export type MeetingHostApi = ReturnType<typeof meetingHostApi>;
