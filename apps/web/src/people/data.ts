// What S-26 Meetings and S-27 My plate read (PPL-40a, FR-PA-03): fixture records shaped by the
// people contracts (contracts/*.schema.json, validated by tests/web/test_PPL_40a_*). Nothing here
// is fetched; the screens say so (PreviewNote). Privacy (ADR-0016, PE-20): of another person only
// the display name is ever read, never an email, alias, time zone or channel.
import type {
  CalendarEntry,
  CalendarEntryAgendaItem,
  CalendarEntryFreeBusy,
  Meeting,
  Mention,
  Minutes,
  Person,
  PinboardItem,
  WorkItem,
} from "@tilo/contracts";
import agendaItems from "./fixtures/agenda_items.json";
import calendarEntries from "./fixtures/calendar_entries.json";
import calendarMeetings from "./fixtures/calendar_meetings.json";
import freeBusy from "./fixtures/free_busy.json";
import meetings from "./fixtures/meetings.json";
import mentions from "./fixtures/mentions.json";
import minutes from "./fixtures/minutes.json";
import persons from "./fixtures/persons.json";
import pins from "./fixtures/pins.json";
import quotes from "./fixtures/quotes.json";
import workItems from "./fixtures/work_items.json";

/** The signed-in person of the preview: the meeting Owner, whose own plate S-27 shows. */
export const SIGNED_IN = "u_owner";
/** The preview's clock. Due dates are measured from here, not from today (HR-1: no invented dates). */
export const PREVIEW_NOW = "2026-10-07T04:00:00.000Z";
export const PREVIEW_TODAY = "2026-10-07";

export const MEETINGS = meetings as unknown as readonly Meeting[];
export const MINUTES = minutes as unknown as readonly Minutes[];
export const WORK_ITEMS = workItems as unknown as readonly WorkItem[];

/** One evidence quote, as the API cuts it from the transcript (PE-05). No contract names this read
 * model yet (docs/open-questions.md), so the shape is this screen's own. */
export interface EvidenceQuote {
  readonly speaker: string;
  readonly text: string;
}
export const QUOTES = quotes as Readonly<Record<string, Readonly<Record<string, EvidenceQuote>>>>;

const PERSONS = persons as unknown as readonly Person[];

// S-28 and S-29 (PPL-40b): pins, tags, calendar entries, the agenda's work-item, meeting and pin
// rows, a teammate's free/busy and the one upcoming meeting. Like the fixtures above, these hold
// other people's records too (a teammate's personal pin and entry): the screens read only what the
// signed-in person may (PE-01, PE-02, PE-04), as the API will.
export const PINS = pins as unknown as readonly PinboardItem[];
export const MENTIONS = mentions as unknown as readonly Mention[];
export const CAL_ENTRIES = calendarEntries as unknown as readonly CalendarEntry[];
export const AGENDA_ROWS = agendaItems as unknown as readonly CalendarEntryAgendaItem[];
export const FREE_BUSY = freeBusy as unknown as readonly CalendarEntryFreeBusy[];
/** Every meeting the calendar knows: S-26's, and the upcoming one the prep view is built for. */
export const ALL_MEETINGS: readonly Meeting[] = [
  ...MEETINGS,
  ...(calendarMeetings as unknown as readonly Meeting[]),
];
/** The signed-in person's own time zone, from their own record (PE-20): the calendar is read in it. */
export const MY_TIME_ZONE = PERSONS.find((p) => p.id === SIGNED_IN)?.time_zone ?? "UTC";

/** The directory view of a person (PE-20): the display name, nothing else. */
export const displayName = (id: string): string =>
  PERSONS.find((p) => p.id === id)?.display_name ?? "A teammate";

/** "You" for the signed-in person, else the teammate's display name. */
export const personName = (id: string): string => (id === SIGNED_IN ? "You" : displayName(id));
