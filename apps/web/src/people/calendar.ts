// What S-29 shows of the calendar, as pure functions over contract-shaped records (FR-CAL-01, -03,
// -05, -06). The agenda is a merge in code, never a model: the person's own entries, then the rows
// of work-item due dates, meetings and pin deadlines. Days are the person's own (their time zone,
// from their own record, PE-20), measured from the preview day, never from the clock (HR-1).
import type {
  CalendarEntry,
  CalendarEntryAgendaItem,
  CalendarEntryFreeBusy,
  Meeting,
  Minutes,
} from "@tilo/contracts";
import { ALL_MEETINGS, MINUTES, MY_TIME_ZONE, PINS, SIGNED_IN, WORK_ITEMS } from "./data";
import { personalBoard, teamBoard } from "./pins";

export const DAY_FROM = 8 * 60; // the availability bars show 08:00 to 20:00
export const DAY_TO = 20 * 60;
const MIN = 60_000;
const DAY = 86_400_000;

const clock = new Intl.DateTimeFormat("en-CA", {
  timeZone: MY_TIME_ZONE,
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** A timestamp on the person's own wall clock: its date and minutes after midnight. */
export function zoned(ts: string | number): { date: string; minutes: number } {
  const p = Object.fromEntries(clock.formatToParts(new Date(ts)).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, minutes: Number(p.hour) * 60 + Number(p.minute) };
}

/** The instant the person's day starts. */
function dayStart(date: string): number {
  const utc = Date.parse(`${date}T00:00:00Z`);
  const offset = (ms: number): number => {
    const z = zoned(ms);
    return Date.parse(`${z.date}T00:00:00Z`) + z.minutes * MIN - ms;
  };
  return utc - offset(utc - offset(utc));
}

export const addDays = (date: string, n: number): string =>
  new Date(Date.parse(`${date}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);

/** The seven days of the week (Monday first) that holds `date`. */
export function weekOf(date: string): string[] {
  const back = (new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7;
  return Array.from({ length: 7 }, (_, i) => addDays(date, i - back));
}

export const hhmm = (minutes: number): string =>
  `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

/** "09:30 to 10:00", "09:30" without an end, "All day". */
export function whenOf(r: CalendarEntryAgendaItem): string {
  if (r.all_day) return "All day";
  const start = hhmm(zoned(r.start).minutes);
  return r.end ? `${start} to ${hhmm(zoned(r.end).minutes)}` : start;
}

/** The person's own entries that are live: accepted, or proposed by Tilo and waiting (FR-CAL-03).
 * A teammate's entry, and a declined or cancelled one, is never on the agenda (PE-04). */
export const ownEntries = (entries: readonly CalendarEntry[], me = SIGNED_IN): CalendarEntry[] =>
  entries.filter((e) => e.owner === me && (e.state === "accepted" || e.state === "proposed"));

const asRow = (e: CalendarEntry): CalendarEntryAgendaItem => ({
  start: e.start,
  end: e.end,
  all_day: e.all_day,
  title: e.title,
  kind: "event",
  source: { kind: "calendar_entry", id: e.id },
  state: e.state === "proposed" ? "proposed" : "confirmed",
  shared: e.share !== null,
});

/** One merged list in a fixed order: all-day first, then by start, title and cited record. */
export function agendaOf(
  entries: readonly CalendarEntry[],
  rows: readonly CalendarEntryAgendaItem[],
): CalendarEntryAgendaItem[] {
  const key = (r: CalendarEntryAgendaItem) => `${r.source.kind}:${r.source.id}`;
  return [...ownEntries(entries).map(asRow), ...rows].sort(
    (a, b) =>
      Number(b.all_day) - Number(a.all_day) ||
      a.start.localeCompare(b.start) ||
      a.title.localeCompare(b.title) ||
      key(a).localeCompare(key(b)),
  );
}

export const onDay = (rows: readonly CalendarEntryAgendaItem[], date: string) =>
  rows.filter((r) => zoned(r.start).date === date);

export interface Bar {
  readonly left: number;
  readonly width: number;
  readonly label: string;
}

/** A teammate's busy intervals on one day, as bars across 08:00 to 20:00 and as words. Intervals
 * only: free/busy has no title to show (PE-04). */
export function barsOn(fb: CalendarEntryFreeBusy, date: string): Bar[] {
  const from = dayStart(date);
  return fb.busy.flatMap((b) => {
    const s = Math.max(0, (Date.parse(b.start) - from) / MIN);
    const e = Math.min(1440, (Date.parse(b.end) - from) / MIN);
    if (e <= s) return [];
    const [l, r] = [Math.max(s, DAY_FROM), Math.min(e, DAY_TO)];
    const span = DAY_TO - DAY_FROM;
    return [
      {
        left: (Math.max(0, l - DAY_FROM) / span) * 100,
        width: (Math.max(0, r - l) / span) * 100,
        label: `Busy ${hhmm(s)} to ${hhmm(e)}`,
      },
    ];
  });
}

export interface Prep {
  readonly previous: readonly { meeting: Meeting; minutes: Minutes }[];
  readonly workItems: readonly { id: string; title: string }[];
  readonly pins: readonly { id: string; title: string }[];
}

const when = (m: Meeting): string => m.scheduled?.start ?? m.created_at;

/** What a meeting row's prep view lists, assembled from records (FR-CAL-05, no model). "Related"
 * means the cited meeting is in the same series or shares an agenda topic; a meeting that kept
 * nothing is not a source. Pins are those the person may read (PE-01, PE-02). */
export function prepFor(m: Meeting): Prep {
  const topics = new Set(m.agenda.map((a) => a.title.toLowerCase()));
  const kept = (o: Meeting) => o.id !== m.id && o.status !== "discarded" && o.status !== "deleted";
  const same = (o: Meeting) => m.series !== null && o.series === m.series;
  const related = new Set(
    ALL_MEETINGS.filter(
      (o) => kept(o) && (same(o) || o.agenda.some((a) => topics.has(a.title.toLowerCase()))),
    ).map((o) => o.id),
  );
  const from = (ref: string | null | undefined) => related.has((ref ?? "").split("#")[0] ?? "");
  const previous = ALL_MEETINGS.filter((o) => kept(o) && same(o) && when(o) < when(m))
    .sort((a, b) => when(b).localeCompare(when(a)))
    .flatMap((meeting) => {
      const minutes = MINUTES.find((x) => x.meeting_id === meeting.id);
      return minutes ? [{ meeting, minutes }] : [];
    });
  return {
    previous,
    workItems: WORK_ITEMS.filter((i) => i.status === "open" && from(i.source.ref)),
    pins: [...teamBoard(PINS), ...personalBoard(PINS)].filter((p) => from(p.source?.ref)),
  };
}
