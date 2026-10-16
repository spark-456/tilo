// FR-MTG-01, FR-MTG-09, FR-MTG-10: the hosted-meeting form rules and the attend window. Kept outside `api/` (which may
// hold no clock, Park's static rule WEB_1a) and outside the Agenda page files (no Date or timers, WEB_9).

/** The notice version the API stamps (`deps.NOTICE_VERSION`); a stale one is a 422. */
export const NOTICE_VERSION = "1.0.0";
/** The disclosed-notetaker notice, from the addendum's rule 2 (PPL: AI notetaker, 30-day transcript, who sees it,
 * `Tilo leave` stops it) and FR-MTG-10 retention. The bot posts the same facts in the meeting chat before it records. */
export const NOTICE_TEXT =
  "I have the right to record this meeting. Tilo joins as an AI notetaker named Tilo notetaker and posts a notice in the meeting chat before it records. The transcript is kept for 30 days and the minutes for 90 days. Only I can see them. Anyone in the meeting can stop it by typing Tilo leave.";
export const LENGTHS = [15, 30, 45] as const; // MH-02: at most 45 minutes (meeting_host.max_duration_min); the bot leaves at 45
/** The "Send Tilo" button shows from this long before the start. */
export const EARLY_MS = 10 * 60_000;

/** The clock and one timer, kept here because the Agenda's page files may use neither (Agenda.static.test). */
export const clockMs = (): number => Date.now();
export function later(fn: () => void, ms: number): () => void {
  const t = setTimeout(fn, ms);
  return () => clearTimeout(t);
}

export interface HostForm {
  title: string;
  /** A `datetime-local` value (`YYYY-MM-DDTHH:mm`), the person's local time. */
  start: string;
  minutes: number;
  attested: boolean;
}

const startMs = (start: string): number => new Date(start).getTime();

/** The first thing wrong with the form, in words, or null. The server still decides. */
export function hostFormError(f: HostForm, nowMs: number): string | null {
  const title = f.title.trim();
  if (!title) return "Give the meeting a title.";
  if (title.length > 120) return "Keep the title to 120 characters.";
  if (/:\/\/|meet\.google\.com/i.test(title)) return "Leave links out of the title.";
  const s = startMs(f.start);
  if (!f.start || Number.isNaN(s)) return "Choose when the meeting starts.";
  if (s <= nowMs) return "Choose a start time in the future.";
  if (!(LENGTHS as readonly number[]).includes(f.minutes))
    return "A hosted meeting lasts 15, 30 or 45 minutes.";
  if (!f.attested) return "Confirm the notice before Tilo can host.";
  return null;
}

/** A person picked from the people list: the id is what the API resolves (only themself or a teammate). */
export interface Picked {
  id: string;
  name: string;
}

/** `POST /v1/meetings`: the attest step is explicit (`attest` true and the notice version shown). */
export function meetingBodyAt(
  title: string,
  startAt: number,
  minutes: number,
  attendees: readonly Picked[] = [],
) {
  const start = new Date(startAt);
  const end = new Date(start.getTime() + minutes * 60_000);
  return {
    attest: true,
    notice_version: NOTICE_VERSION,
    title,
    source: "bot",
    scheduled: { start: start.toISOString(), end: end.toISOString() },
    attendees: attendees.map((p) => ({ name: p.name, person: p.id })),
  };
}

export const meetingBody = (f: HostForm, attendees: readonly Picked[] = []) =>
  meetingBodyAt(f.title.trim(), startMs(f.start), f.minutes, attendees);

/** "Meet with Tilo now": a 45 minute meeting that starts two minutes from now (the host rule wants a start in the
 * future; the person is in Meet well before it). Only the person who clicked is invited. */
export const MEET_NOW_TITLE = "Meeting with Tilo";
export const MEET_NOW_LEAD_MS = 2 * 60_000;
export const MEET_NOW_MINUTES = 45;
export const meetNowBody = (nowMs: number) =>
  meetingBodyAt(MEET_NOW_TITLE, nowMs + MEET_NOW_LEAD_MS, MEET_NOW_MINUTES);

/** The one line the person sees next to "Meet with Tilo now"; starting it is their own confirmation. */
export const MEET_NOW_NOTICE =
  "Starting this confirms you may record it. Tilo joins as an AI notetaker named Tilo notetaker and posts a notice in the meeting chat. Only you can see the transcript, kept for 30 days. Anyone can stop Tilo by typing Tilo leave.";

/** A tab opened on the click itself (so a pop-up blocker allows it) and pointed at Meet once the link is known. */
export interface MeetTab {
  go(url: string): void;
  close(): void;
}
export function openMeetTab(): MeetTab | null {
  try {
    const w = window.open("about:blank", "_blank");
    if (!w) return null;
    w.opener = null;
    return {
      go: (url) => {
        w.location.href = url;
      },
      close: () => w.close(),
    };
  } catch {
    return null;
  }
}

export interface HostableRow {
  source: string | null;
  status: string;
  at: string;
  end: string | null;
}
/** From 10 minutes before the start until the end (no end recorded: an hour, the hosted cap). */
export function attendOffered(row: HostableRow, nowMs: number): boolean {
  if (row.source !== "bot" || row.status !== "scheduled") return false;
  const s = new Date(row.at).getTime();
  if (Number.isNaN(s)) return false;
  const e = row.end ? new Date(row.end).getTime() : s + 60 * 60_000;
  return nowMs >= s - EARLY_MS && nowMs <= e;
}
