// FR-AGT-14 (PRD 8, "Scheduled runs"): the web's side of services/api `/schedules`
// (services/api/src/tilo_api/schedules.py). The routes are not on the frozen TiloClient interface
// (like `pauseWorld`), so a client that has them is detected here, never added there.
import type { TiloClient } from "./client";

/** When a routine fires: weekday 0 = Monday .. 6 = Sunday (services/harness schedule.py `Cadence`). */
export interface Cadence {
  readonly weekday: number;
  readonly hour: number;
  readonly minute: number;
  /** An IANA zone name, e.g. `Asia/Kolkata`. */
  readonly tz: string;
}

/** What `GET /schedules` returns for one routine. Only the fields the page reads are typed. */
export interface ScheduleView {
  readonly schedule_id: string;
  readonly title: string;
  readonly cadence: Cadence;
  readonly enabled: boolean;
  readonly next_due: string | null;
}

/** `POST /schedules`: the task whose budget was approved, the approach chosen, a title and the cadence. */
export interface ScheduleRequest {
  readonly task_id: string;
  readonly approach_id: string;
  readonly title: string;
  readonly cadence: Cadence;
}

export interface SchedulesApi {
  listSchedules(): Promise<ScheduleView[]>;
  createSchedule(req: ScheduleRequest): Promise<ScheduleView>;
  updateSchedule(id: string, patch: { enabled?: boolean; title?: string }): Promise<ScheduleView>;
  deleteSchedule(id: string): Promise<void>;
}

export const canSchedule = (client: TiloClient): client is TiloClient & SchedulesApi =>
  typeof (client as Partial<SchedulesApi>).listSchedules === "function";

const whole = (n: unknown, max: number): boolean =>
  typeof n === "number" && Number.isInteger(n) && n >= 0 && n <= max;

/** Whether a reply row has the shape the page reads; anything else is an unreadable reply. */
export const isScheduleView = (v: unknown): v is ScheduleView => {
  const s = v as Partial<ScheduleView> | null;
  const c = s?.cadence;
  return (
    typeof s === "object" &&
    s !== null &&
    typeof s.schedule_id === "string" &&
    typeof s.title === "string" &&
    typeof s.enabled === "boolean" &&
    (s.next_due === null || typeof s.next_due === "string") &&
    typeof c === "object" &&
    c !== null &&
    whole(c.weekday, 6) &&
    whole(c.hour, 23) &&
    whole(c.minute, 59) &&
    typeof c.tz === "string"
  );
};

export const WEEKDAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

const two = (n: number): string => String(n).padStart(2, "0");

/** "Every Monday at 09:00 (Asia/Kolkata)". */
export const cadenceWords = (c: Cadence): string =>
  `Every ${WEEKDAYS[c.weekday]} at ${two(c.hour)}:${two(c.minute)} (${c.tz})`;

/** The next run in the routine's own zone, e.g. "Mon 12 Oct, 09:00"; the raw time if the zone is unknown. */
export function nextRunWords(nextDue: string | null, tz: string): string {
  if (nextDue === null) return "not scheduled";
  const at = new Date(nextDue);
  if (Number.isNaN(at.getTime())) return nextDue;
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(at);
  } catch {
    return nextDue;
  }
}
