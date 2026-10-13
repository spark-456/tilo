import { type HttpClient, TiloApiError } from "../../../api/http";

export interface PeopleRow {
  id: string;
  title: string;
  status: string;
  at: string;
  body: string | null;
  scope: string | null;
  setter: string | null;
  personalUser: string | null;
}
export interface PeopleList {
  rows: PeopleRow[];
  truncated: boolean;
}
const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === "string" && v.trim().length > 0;
const bad = () => new TiloApiError("Unreadable people list reply", 200, true);
export function peopleListFromReply(v: unknown, kind: "meetings" | "pinboards"): PeopleList {
  if (!object(v) || !Array.isArray(v.items) || typeof v.truncated !== "boolean") throw bad();
  const rows = v.items.map((r): PeopleRow => {
    if (
      !object(r) ||
      !text(r.id) ||
      !new RegExp(kind === "meetings" ? "^mt_[A-Za-z0-9_]{1,48}$" : "^pb_[A-Za-z0-9_]{1,48}$").test(
        r.id,
      ) ||
      !text(r.title) ||
      !text(r.created_at) ||
      !text(r.status)
    )
      throw bad();
    let at = r.created_at;
    let body: string | null = null;
    let scope: string | null = null;
    let setter: string | null = null;
    let personalUser: string | null = null;
    if (kind === "meetings") {
      if (
        !["scheduled", "joining", "live", "ended", "minuted", "discarded", "deleted"].includes(
          r.status,
        )
      )
        throw bad();
      if (r.scheduled !== null) {
        if (!object(r.scheduled) || !text(r.scheduled.start)) throw bad();
        at = r.scheduled.start;
      }
    } else {
      if (
        !["active", "proposed", "removed"].includes(r.status) ||
        !(r.body === null || typeof r.body === "string") ||
        !object(r.scope)
      )
        throw bad();
      if (r.scope.kind === "personal" && text(r.scope.user)) scope = "Personal";
      else if (r.scope.kind === "team" && text(r.scope.team)) scope = `Team ${r.scope.team}`;
      else throw bad();
      body = r.body;
      setter = text(r.set_up_by) ? r.set_up_by : null;
      personalUser = r.scope.kind === "personal" ? String(r.scope.user) : null;
    }
    return { id: r.id, title: r.title, status: r.status, at, body, scope, setter, personalUser };
  });
  if (new Set(rows.map((r) => r.id)).size !== rows.length) throw bad();
  return {
    rows: rows.filter((r) => r.status !== "deleted" && r.status !== "removed"),
    truncated: v.truncated,
  };
}
/** A dedicated seam keeps the original Park fixture interface and its assertions intact. */
export function peopleListsApi(http: Pick<HttpClient, "getJson">) {
  const get = async (kind: "meetings" | "pinboards") => ({
    data: peopleListFromReply(await http.getJson(`/v1/${kind}`), kind),
    source: "live" as const,
  });
  return { getMeetings: () => get("meetings"), getPinboards: () => get("pinboards") };
}
