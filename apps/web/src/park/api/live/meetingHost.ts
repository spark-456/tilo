// FR-MTG-01, FR-MTG-09, FR-MTG-10 (ADR-0024, ADR-0032, MEET-SIMPLE): the Agenda's calls for a Tilo-hosted Google Meet.
// create -> world -> start is the owner's own click (`start` hosts the meeting and records their confirmation as the
// approval, in one request); `attend` is one long-held request that ends when the bot leaves, and the API itself wakes
// a cold bot and asks again until it starts. Nothing here retries, and nothing is "started" unless the API's reply
// said so. Request bodies follow `services/api people_writes.MeetingIn` (attest, notice_version, title, source,
// scheduled, attendees) and `StartIn` (approve, invited).
import { type HttpClient, TiloApiError } from "../../../api/http";
import {
  type HostForm,
  type Picked,
  meetNowBody,
  meetingBody,
} from "../../shared/hostMeetingRules";

const ID = /^mt_[A-Za-z0-9_]{1,48}$/;
export const MEET = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/;
const bad = () => new TiloApiError("The meeting reply could not be read.", 200, false);
const isObject = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);

const made = (reply: unknown): string => {
  if (!isObject(reply) || typeof reply.id !== "string" || !ID.test(reply.id)) throw bad();
  return reply.id;
};

/** How a captured meeting ended, from the stored `ended_reason` (meeting.schema.json). */
export const ENDED_TEXT: Readonly<Record<string, string>> = {
  completed: "The meeting ended and Tilo left.",
  left_on_request: "Someone typed Tilo leave, so Tilo left.",
  removed: "Tilo was removed from the meeting.",
  timeout: "Tilo waited and was not admitted, or the call timed out, so it left.",
  failed: "Tilo could not stay in the meeting.",
};

const isPerson = (v: unknown): v is { id: string; display_name: string } =>
  isObject(v) && typeof v.id === "string" && typeof v.display_name === "string" && v.id.length > 0;

export function meetingHostApi(http: Pick<HttpClient, "getJson" | "postJson">) {
  const path = (id: string, action: string) => {
    if (!ID.test(id)) throw bad();
    return `/v1/meetings/${id}/${action}`;
  };
  return {
    /** The people the signed-in person may pick, and who they are (`GET /v1/people`: ids and names only). */
    async people(): Promise<{ you: string; people: Picked[] }> {
      const r = await http.getJson("/v1/people");
      if (!isObject(r) || typeof r.you !== "string" || !Array.isArray(r.people)) throw bad();
      return {
        you: r.you,
        people: r.people.filter(isPerson).map((p) => ({ id: p.id, name: p.display_name })),
      };
    },
    /** Step 1. The key makes one tap one meeting even if the same request is sent twice. */
    async create(f: HostForm, key: string, attendees: readonly Picked[] = []): Promise<string> {
      return made(
        await http.postJson("/v1/meetings", meetingBody(f, attendees), { "Idempotency-Key": key }),
      );
    },
    /** The same, for "Meet with Tilo now" (title, start and length are fixed; nobody else is invited). */
    async createNow(nowMs: number, key: string): Promise<string> {
      return made(
        await http.postJson("/v1/meetings", meetNowBody(nowMs), { "Idempotency-Key": key }),
      );
    },
    /** Step 3 (replaces `host`): the person's own click is the approval. `invited` is exactly who they were shown.
     * The reply comes once the invitation has gone out. */
    async start(id: string, invited: readonly string[]): Promise<void> {
      const r = await http.postJson(path(id, "start"), { approve: true, invited });
      if (!isObject(r) || typeof r.world_id !== "string") throw bad();
    },
    /** Takes back a meeting whose start failed (nothing was sent), so no half-made meeting stays on the Agenda. */
    async remove(id: string): Promise<void> {
      await http.postJson(path(id, "delete"), {});
    },
    /** Step 2: the meeting's world, written once. */
    async world(id: string): Promise<void> {
      await http.postJson(path(id, "world"), {});
    },
    /** One request held open until the bot leaves (up to about 45 minutes). With `joinUrl` (MEET-GUEST) Tilo's guest
     * bot goes to the person's own Google Meet and the host admits it: no meeting host account is involved. */
    async attend(id: string, joinUrl?: string): Promise<{ status: string; reason: string | null }> {
      const r = await http.postJson(path(id, "attend"), joinUrl ? { join_url: joinUrl } : {});
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
