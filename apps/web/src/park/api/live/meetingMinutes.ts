import { type HttpClient, TiloApiError } from "../../../api/http";

const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const bad = () => new TiloApiError("The meeting reply could not be read.", 200, false);
export interface MinutesView {
  summary: string[];
  decisions: string[];
  actions: string[];
  /** MINUTES-ME: the Owner first as "Me" (`self`), then the attendees with a linked person record. */
  recipients: { id: string; name: string; self?: boolean }[];
}
/** MINUTES-ME: a transcript read that has not answered by then says so instead of waiting for ever. */
export const TRANSCRIPT_WAIT_MS = 20_000;
/** MINUTES-SCREEN: the owner's own transcript, each line as the server's owner quotes show it (cleaned, redacted). */
export interface TranscriptView {
  lines: { id: string; speaker: string | null; text: string; atMs: number }[];
  /** What the safety check said of the stored transcript: clean, flagged or unscreened. */
  screening: string;
}
export interface DraftCard {
  cardId: string;
  subject: string;
  body: string;
  recipients: string[];
}
/** Reuse the authenticated, App Check protected client. No capability probe: a route the server never installed answers 404 to the real call and the control hides itself. */
export function meetingMinutesApi(http: Pick<HttpClient, "getJson" | "postJson">) {
  const path = (id: string, action: string) => {
    if (!/^mt_[A-Za-z0-9_]{1,48}$/.test(id)) throw bad();
    return `/v1/meetings/${id}/${action}`;
  };
  const texts = (v: unknown): string[] => {
    if (!Array.isArray(v) || !v.every((r) => object(r) && typeof r.text === "string")) throw bad();
    return v.map((r) => `${r.text}${typeof r.state === "string" ? ` (${r.state})` : ""}`);
  };
  return {
    async read(id: string): Promise<{ minutes: MinutesView; confirmed: boolean }> {
      const meeting = await http.getJson(`/v1/meetings/${encodeURIComponent(id)}`);
      const doc = await http.getJson(path(id, "minutes"));
      if (!object(meeting) || meeting.id !== id || !object(doc) || doc.meeting_id !== id)
        throw bad();
      if (!Array.isArray(meeting.attendees)) throw bad();
      const owner =
        typeof meeting.owner === "string" && /^u_[A-Za-z0-9_]{1,48}$/.test(meeting.owner)
          ? meeting.owner
          : null;
      const recipients: MinutesView["recipients"] = [
        ...(owner ? [{ id: owner, name: "Me", self: true }] : []),
        ...meeting.attendees.flatMap((a) =>
          object(a) &&
          typeof a.user === "string" &&
          /^u_[A-Za-z0-9_]{1,48}$/.test(a.user) &&
          a.user !== owner &&
          typeof a.name === "string"
            ? [{ id: a.user, name: a.name }]
            : [],
        ),
      ];
      return {
        minutes: {
          summary: texts(doc.summary),
          decisions: texts(doc.decisions),
          actions: texts(doc.action_items),
          recipients: Array.from(new Map(recipients.map((r) => [r.id, r])).values()),
        },
        confirmed: object(meeting.minutes_confirmed_by),
      };
    },
    async analyze(id: string) {
      await http.postJson(path(id, "analyze-minutes"), {});
    },
    async transcript(id: string): Promise<TranscriptView> {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const late = new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new TiloApiError("The transcript took too long.", null, true)),
          TRANSCRIPT_WAIT_MS,
        );
      });
      const doc = await Promise.race([http.getJson(path(id, "transcript")), late]).finally(() =>
        clearTimeout(timer),
      );
      if (
        !object(doc) ||
        doc.meeting_id !== id ||
        typeof doc.screening !== "string" ||
        !Array.isArray(doc.utterances)
      )
        throw bad();
      const lines = doc.utterances.map((u) => {
        if (
          !object(u) ||
          typeof u.id !== "string" ||
          typeof u.text !== "string" ||
          typeof u.t_ms !== "number" ||
          !(u.speaker === null || typeof u.speaker === "string")
        )
          throw bad();
        return { id: u.id, speaker: u.speaker as string | null, text: u.text, atMs: u.t_ms };
      });
      return { lines, screening: doc.screening };
    },
    async confirm(id: string) {
      const reply = await http.postJson(path(id, "confirm"), {});
      if (!object(reply) || reply.id !== id || !object(reply.minutes_confirmed_by)) throw bad();
    },
    /** MINUTES-ALL: the Owner's send list: names, the address on record or none, and whether the transcript can go. */
    async sendList(id: string): Promise<SendList> {
      const doc = await http.getJson(path(id, "followup-recipients"));
      if (!object(doc) || doc.meeting_id !== id || !Array.isArray(doc.recipients)) throw bad();
      const people = doc.recipients.map((r) => {
        if (
          !object(r) ||
          typeof r.name !== "string" ||
          !(r.email === null || typeof r.email === "string") ||
          !["owner", "invited", "heard"].includes(String(r.source))
        )
          throw bad();
        return { name: r.name, email: r.email as string | null, source: r.source as SendSource };
      });
      return { people, transcript: doc.transcript === true };
    },
    /** MINUTES-ALL: one email with the minutes (and the transcript when asked) to the addresses the Owner reviewed. */
    async draftToAll(id: string, addresses: string[], transcript: boolean): Promise<DraftCard[]> {
      if (!addresses.length || addresses.length > 50 || addresses.some((a) => !isMailbox(a)))
        throw bad();
      return cards(await http.postJson(path(id, "draft-followup"), { addresses, transcript }));
    },
    async draft(id: string, recipients: string[]): Promise<DraftCard[]> {
      if (
        !recipients.length ||
        recipients.some((r) => !/^u_[A-Za-z0-9_]{1,48}$/.test(r)) ||
        new Set(recipients).size !== recipients.length ||
        recipients.length > 50
      )
        throw bad();
      return cards(await http.postJson(path(id, "draft-followup"), { recipients }));
    },
  };
}
export type MeetingMinutesApi = ReturnType<typeof meetingMinutesApi>;
export type SendSource = "owner" | "invited" | "heard";
export interface SendList {
  people: { name: string; email: string | null; source: SendSource }[];
  transcript: boolean;
}
/** One bare mailbox: no display name, no list, no spaces (the server checks it again, strictly). */
export const isMailbox = (value: string): boolean =>
  value.length <= 254 && /^[^\s@,;<>"]+@[^\s@,;<>"]+\.[^\s@,;<>".]{2,}$/.test(value);

function cards(reply: unknown): DraftCard[] {
  const rows = reply === null ? [] : Array.isArray(reply) ? reply : [reply];
  return rows.map((r) => {
    if (
      !object(r) ||
      typeof r.card_id !== "string" ||
      typeof r.subject !== "string" ||
      typeof r.body !== "string" ||
      r.tier !== "T3" ||
      !Array.isArray(r.to) ||
      !r.to.every((v) => typeof v === "string")
    )
      throw bad();
    return {
      cardId: r.card_id,
      subject: r.subject,
      body: r.body,
      recipients: r.to as string[],
    };
  });
}
