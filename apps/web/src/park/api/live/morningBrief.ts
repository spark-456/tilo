import { type HttpClient, TiloApiError } from "../../../api/http";

// Home imports the error class from here, so a page never reaches outside park/ (WEB_4 static rule).
export { TiloApiError };

export type BriefSource = {
  kind: "calendar_event" | "mail" | "work_item" | "pinboard_item" | "world";
  id: string;
};
export type BriefItem = { source: BriefSource } & Record<string, unknown>;
type MailItem = BriefItem & {
  from_name: string | null;
  subject: string | null;
  received_at: string | null;
};
export interface MorningBrief {
  v: "1.0";
  owner: string;
  local_date: string;
  time_zone: string;
  generated_at: string;
  trigger: "schedule" | "on_demand";
  model: "used" | "skipped" | "failed" | "flagged";
  meetings: {
    status: "ok" | "not_connected" | "unavailable";
    items: (BriefItem & { title: string; start: string })[];
  };
  mail_needing_reply: {
    status: "ok" | "unsorted" | "not_connected" | "unavailable";
    items: MailItem[];
  };
  deadlines: {
    status: "ok" | "unavailable";
    items: (BriefItem & { title: string; due: string })[];
  };
  suggestions: { text: string; cites: BriefSource[] }[];
  todo_suggestions: { title: string; due_text: string | null; mail: MailItem }[];
}
export interface BriefSettings {
  owner_id: string;
  org_id: string;
  enabled: boolean;
  time: string;
  time_zone: string;
  email_copy: boolean;
  email_rule_ready: boolean;
  updated_at: string | null;
}
export type BriefSettingsUpdate = Pick<
  BriefSettings,
  "enabled" | "time" | "time_zone" | "email_copy"
>;

const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const list = (v: unknown): v is unknown[] => Array.isArray(v);
const source = (v: unknown): v is BriefSource =>
  object(v) &&
  ["calendar_event", "mail", "work_item", "pinboard_item", "world"].includes(String(v.kind)) &&
  typeof v.id === "string" &&
  /^[A-Za-z0-9_-]{1,128}$/.test(v.id);
const section = (v: unknown): v is { status: string; items: unknown[] } =>
  object(v) && typeof v.status === "string" && list(v.items);
const bad = () => new TiloApiError("Tilo sent a brief this page could not read.", 200, false);
const mail = (v: unknown): v is MailItem =>
  object(v) &&
  source(v.source) &&
  (v.from_name === null || typeof v.from_name === "string") &&
  (v.subject === null || typeof v.subject === "string") &&
  (v.received_at === null || typeof v.received_at === "string");
function briefOf(v: unknown): MorningBrief {
  if (
    !object(v) ||
    v.v !== "1.0" ||
    typeof v.owner !== "string" ||
    typeof v.local_date !== "string" ||
    typeof v.time_zone !== "string" ||
    typeof v.generated_at !== "string" ||
    !["schedule", "on_demand"].includes(String(v.trigger)) ||
    !["used", "skipped", "failed", "flagged"].includes(String(v.model)) ||
    !section(v.meetings) ||
    !section(v.mail_needing_reply) ||
    !section(v.deadlines) ||
    !["ok", "not_connected", "unavailable"].includes(v.meetings.status) ||
    !["ok", "unsorted", "not_connected", "unavailable"].includes(v.mail_needing_reply.status) ||
    !["ok", "unavailable"].includes(v.deadlines.status) ||
    !list(v.suggestions) ||
    !list(v.todo_suggestions) ||
    !v.meetings.items.every((x) => object(x) && source(x.source) && typeof x.title === "string") ||
    !v.mail_needing_reply.items.every(mail) ||
    !v.deadlines.items.every((x) => object(x) && source(x.source) && typeof x.title === "string") ||
    !v.suggestions.every(
      (x) => object(x) && typeof x.text === "string" && list(x.cites) && x.cites.every(source),
    ) ||
    !v.todo_suggestions.every((x) => object(x) && typeof x.title === "string" && mail(x.mail))
  )
    throw bad();
  return v as unknown as MorningBrief;
}
function settingsOf(v: unknown): BriefSettings {
  if (
    !object(v) ||
    typeof v.enabled !== "boolean" ||
    typeof v.time !== "string" ||
    typeof v.time_zone !== "string" ||
    typeof v.email_copy !== "boolean" ||
    typeof v.email_rule_ready !== "boolean"
  )
    throw bad();
  return v as unknown as BriefSettings;
}

/** Auth and App Check are supplied by Park's existing HttpClient. */
export function morningBriefApi(http: Pick<HttpClient, "getJson" | "postJson" | "putJson">) {
  return {
    async read() {
      return briefOf(await http.getJson("/v1/me/brief"));
    },
    async make() {
      return briefOf(await http.postJson("/v1/me/brief", {}));
    },
    async settings() {
      return settingsOf(await http.getJson("/v1/me/brief-settings"));
    },
    async saveSettings(update: BriefSettingsUpdate) {
      return settingsOf(await http.putJson("/v1/me/brief-settings", update));
    },
    async addTodo(todo: MorningBrief["todo_suggestions"][number]) {
      if (todo.mail.source.kind !== "mail") throw bad();
      const reply = await http.postJson("/v1/work-items", {
        title: todo.title,
        ...(todo.due_text ? { due_text: todo.due_text } : {}),
        source: { kind: "mail", ref: todo.mail.source.id },
      });
      if (
        !object(reply) ||
        typeof reply.id !== "string" ||
        typeof reply.title !== "string" ||
        reply.status !== "open"
      )
        throw bad();
      return { id: reply.id, title: reply.title };
    },
  };
}
export type MorningBriefApi = ReturnType<typeof morningBriefApi>;
