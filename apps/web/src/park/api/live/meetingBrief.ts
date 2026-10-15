import { type HttpClient, TiloApiError } from "../../../api/http";

const object = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === "object" && !Array.isArray(v);
const bad = () => new TiloApiError("The meeting brief could not be read.", 200, false);
const meetingId = (id: string) => {
  if (!/^mt_[A-Za-z0-9_]{1,48}$/.test(id)) throw bad();
  return `/v1/meetings/${id}`;
};

export type BriefSource = {
  kind: "agenda" | "prior";
  index?: number;
  meeting_id?: string;
  item?: string;
};
export interface BriefDocument {
  meeting_id: string;
  flagged: boolean;
  agenda_points: {
    title: string;
    minutes: number | null;
    talk_points: { text: string; evidence: BriefSource[] }[];
  }[];
  carry_over: {
    text: string;
    kind: "decision" | "open_action";
    from_meeting: string;
    item: string;
  }[];
}
export type BriefMeeting = { briefRequested: boolean; autoReport: boolean };
const isText = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const isBool = (v: unknown) => v === undefined || typeof v === "boolean";
const isSource = (v: unknown): v is BriefSource =>
  object(v) &&
  (v.kind === "agenda"
    ? Number.isInteger(v.index) && (v.index as number) >= 0
    : v.kind === "prior" && isText(v.meeting_id) && isText(v.item));
function documentOf(value: unknown, id: string): BriefDocument {
  if (
    !object(value) ||
    value.v !== "1.0" ||
    value.meeting_id !== id ||
    typeof value.flagged !== "boolean" ||
    !Array.isArray(value.agenda_points) ||
    !Array.isArray(value.carry_over)
  )
    throw bad();
  const point = (p: unknown) =>
    object(p) &&
    isText(p.title) &&
    (p.minutes === null || typeof p.minutes === "number") &&
    Array.isArray(p.talk_points) &&
    p.talk_points.every(
      (t: unknown) =>
        object(t) && isText(t.text) && Array.isArray(t.evidence) && t.evidence.every(isSource),
    );
  const carry = (c: unknown) =>
    object(c) &&
    isText(c.text) &&
    (c.kind === "decision" || c.kind === "open_action") &&
    isText(c.from_meeting) &&
    isText(c.item);
  if (!value.agenda_points.every(point) || !value.carry_over.every(carry)) throw bad();
  return value as unknown as BriefDocument;
}

/** The owner-only brief routes use the same authenticated client as minutes. No automatic POST. */
export function meetingBriefApi(http: Pick<HttpClient, "getJson" | "postJson" | "sendJson">) {
  return {
    async meeting(id: string): Promise<BriefMeeting> {
      const value = await http.getJson(meetingId(id));
      if (
        !object(value) ||
        value.id !== id ||
        !isBool(value.brief_requested) ||
        !isBool(value.auto_report)
      )
        throw bad();
      return {
        briefRequested: value.brief_requested === true,
        autoReport: value.auto_report === true,
      };
    },
    async read(id: string): Promise<BriefDocument | null> {
      try {
        return documentOf(await http.getJson(`${meetingId(id)}/brief`), id);
      } catch (error) {
        if (error instanceof TiloApiError && error.status === 404 && error.code === "not_ready")
          return null;
        throw error;
      }
    },
    async generate(id: string): Promise<BriefDocument> {
      return documentOf(await http.postJson(`${meetingId(id)}/brief`, {}), id);
    },
    async switch(
      id: string,
      key: "brief_requested" | "auto_report",
      on: boolean,
    ): Promise<Partial<BriefMeeting>> {
      const value = await http.sendJson("PATCH", meetingId(id), { [key]: on });
      if (
        !object(value) ||
        value.id !== id ||
        !isBool(value.brief_requested) ||
        !isBool(value.auto_report)
      )
        throw bad();
      return {
        ...(key === "brief_requested" ? { briefRequested: on } : {}),
        ...(key === "auto_report" ? { autoReport: on } : {}),
      };
    },
  };
}
export type MeetingBriefApi = ReturnType<typeof meetingBriefApi>;
