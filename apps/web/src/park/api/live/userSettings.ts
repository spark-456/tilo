import type { UserSettings } from "@tilo/contracts";

const ROWS = ["decisions", "spend", "finished", "digest", "weekly"] as const;
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const isText = (v: unknown): v is string => typeof v === "string";

/** FR-SET-01/02: only a document with every field the Profile page reads is a UserSettings; anything else is
 * an unreadable reply, never defaults the page would show as the person's own. */
export function isUserSettings(v: unknown): v is UserSettings {
  if (!isObject(v) || !Number.isInteger(v.version)) return false;
  const { profile: p, notifications: n, quiet_hours: q } = v;
  if (!isObject(p) || !isObject(n) || !isObject(q) || !isObject(p.working_hours)) return false;
  return (
    [p.name, p.email, p.time_zone, p.language, q.start, q.end].every(isText) &&
    (p.title === null || isText(p.title)) &&
    Array.isArray(p.working_hours.days) &&
    isText(p.working_hours.start) &&
    isText(p.working_hours.end) &&
    typeof q.enabled === "boolean" &&
    ROWS.every((id) => {
      const r = n[id];
      return isObject(r) && [r.phone, r.email, r.slack].every((b) => typeof b === "boolean");
    })
  );
}
