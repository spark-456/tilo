// FR-SET-01 / FR-SET-02 (ADR-0039): the Profile form's six text fields and the notification rows, to and from the
// stored UserSettings document. Pure: no network and no storage. The server (USET-03) stays the judge of a value;
// this only turns text into the contract's shapes and says in plain words why a save did not happen.
import type {
  UserSettings,
  UserSettingsNotifications,
  UserSettingsProfile,
  UserSettingsWeekday,
  UserSettingsWorkingHours,
} from "@tilo/contracts";
import { displayApiError } from "../../api/errorMessage";

export const FORM_KEYS = ["name", "email", "title", "tz", "lang", "hours"] as const;
export type Form = Record<(typeof FORM_KEYS)[number], string>;
export type RowId = keyof UserSettingsNotifications;
/** One matrix row in column order: phone, email, Slack. */
export type Channels = [boolean, boolean, boolean];

const DAYS: UserSettingsWeekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const LANGS: Record<string, string> = {
  en: "English",
  "en-GB": "English (UK)",
  "en-US": "English (US)",
  "en-IN": "English (India)",
};
const HOURS = /^(\d{2}:\d{2})\s*(?:–|-|to)\s*(\d{2}:\d{2})\s*,\s*(.+)$/;
export const HOURS_FORMAT =
  "Write working hours like 08:30 – 17:30, Monday to Friday. Nothing was saved.";

const dayIndex = (word: string): number => {
  const w = word.trim().toLowerCase();
  return w.length >= 3 ? NAMES.findIndex((n) => n.toLowerCase().startsWith(w)) : -1;
};

function daysText(days: readonly UserSettingsWeekday[]): string {
  const at = DAYS.flatMap((d, i) => (days.includes(d) ? [i] : []));
  const [first = 0] = at;
  const last = at[at.length - 1] ?? 0;
  if (at.length === 7) return "Every day";
  if (at.length >= 3 && last - first + 1 === at.length) return `${NAMES[first]} to ${NAMES[last]}`;
  return at.map((i) => NAMES[i]).join(", ");
}

function parseDays(text: string): UserSettingsWorkingHours["days"] | null {
  const t = text.trim().toLowerCase();
  const range = /^([a-z]+)\s*(?:to|-|–)\s*([a-z]+)$/.exec(t);
  const picks = range
    ? [dayIndex(range[1] ?? ""), dayIndex(range[2] ?? "")]
    : t.split(/\s*(?:,|\band\b)\s*/).map(dayIndex);
  if (t === "every day") return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  if (picks.some((i) => i < 0)) return null;
  const [from = 0, to = 0] = picks;
  const want = range
    ? DAYS.filter((_, i) => i >= from && i <= to)
    : DAYS.filter((_, i) => picks.includes(i));
  const [head, ...rest] = want;
  return head ? [head, ...rest] : null;
}

export const formOf = (p: UserSettingsProfile): Form => ({
  name: p.name,
  email: p.email,
  title: p.title ?? "",
  tz: p.time_zone,
  lang: LANGS[p.language] ?? p.language,
  hours: `${p.working_hours.start} – ${p.working_hours.end}, ${daysText(p.working_hours.days)}`,
});

/** The form as a profile, or null when the working hours cannot be read (the server never sees a guess). */
export function profileOf(f: Form): UserSettingsProfile | null {
  const m = HOURS.exec(f.hours.trim());
  const days = m ? parseDays(m[3] ?? "") : null;
  if (!m || !days) return null;
  const lang = f.lang.trim();
  const tag = Object.entries(LANGS).find(([, l]) => l.toLowerCase() === lang.toLowerCase())?.[0];
  return {
    name: f.name.trim(),
    email: f.email.trim(),
    title: f.title.trim() || null,
    time_zone: f.tz.trim(),
    language: tag ?? lang,
    working_hours: { days, start: m[1] ?? "", end: m[2] ?? "" },
  };
}

/** The form a person starts from. Nothing saved yet (version 0) shows who they signed in as, not the server's placeholder. */
export function baseForm(
  doc: UserSettings,
  who: { name: string; email: string; tz: string },
): Form {
  const f = formOf(doc.profile);
  if (doc.version > 0) return f;
  return { ...f, name: who.name || f.name, email: who.email || f.email, tz: who.tz || f.tz };
}

export const channelsOf = (doc: UserSettings, id: RowId): Channels => {
  const r = doc.notifications[id];
  return [r.phone, r.email, r.slack];
};

export function notificationsOf(rowOf: (id: RowId) => Channels): UserSettingsNotifications {
  const row = (id: RowId) => {
    const [phone, email, slack] = rowOf(id);
    return { phone, email, slack };
  };
  return {
    decisions: row("decisions"),
    spend: row("spend"),
    finished: row("finished"),
    digest: row("digest"),
    weekly: row("weekly"),
  };
}

interface Failure {
  name?: string;
  status?: number | null;
  code?: string | null;
  message?: string;
}
export const isConflict = (e: unknown): boolean =>
  (e as Failure | null)?.code === "version_conflict";

/** What a person reads when settings could not be read or saved. Never says a save happened. */
export function problemOf(e: unknown, saving: boolean): string {
  const f = (e ?? {}) as Failure;
  const unsaved = saving ? " Nothing was saved." : "";
  if (f.name === "NotBuilt") return `Settings are not connected to this Tilo yet.${unsaved}`;
  if (f.status === 401) return `Sign in to see and save your settings.${unsaved}`;
  if (isConflict(e))
    return "These settings changed on another device. Nothing was saved. Reload to see the latest.";
  if (f.code === "invalid_settings")
    return "Tilo could not accept one of the values. Nothing was saved. Check the fields and try again.";
  const said = displayApiError(e);
  if (saving && (f.code === "write_unconfirmed" || f.status === null))
    return `${said} Your changes are still here.`;
  return saving ? `${said} Nothing was saved. Your changes are still here.` : said;
}

/**
 * Issue 588 / BQ-SETWEB-1: the design shows "(GMT+1)" beside the zone. A display-only label for an IANA name
 * ("Europe/London" -> "GMT+1" in summer); null for anything the runtime does not know. It is never saved.
 */
export function gmtLabel(zone: string, at: Date = new Date()): string | null {
  try {
    const parts = new Intl.DateTimeFormat("en", {
      timeZone: zone.trim(),
      timeZoneName: "shortOffset",
    }).formatToParts(at);
    const label = parts.find((p) => p.type === "timeZoneName")?.value;
    // ICU versions differ on zero-offset spelling; keep the display label stable.
    return label?.replace(/^GMT[+-]0(?::00)?$/, "GMT") ?? null;
  } catch {
    return null;
  }
}
