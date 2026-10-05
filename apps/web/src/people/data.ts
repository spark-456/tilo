// What S-26 Meetings and S-27 My plate read (PPL-40a, FR-PA-03): fixture records shaped by the
// people contracts (contracts/*.schema.json, validated by tests/web/test_PPL_40a_*). Nothing here
// is fetched; the screens say so (PreviewNote). Privacy (ADR-0016, PE-20): of another person only
// the display name is ever read, never an email, alias, time zone or channel.
import type { Meeting, Minutes, Person, WorkItem } from "@tilo/contracts";
import meetings from "./fixtures/meetings.json";
import minutes from "./fixtures/minutes.json";
import persons from "./fixtures/persons.json";
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

/** "You" for the signed-in person, else the directory view of a teammate: the display name only. */
export const personName = (id: string): string =>
  id === SIGNED_IN
    ? "You"
    : ((persons as unknown as readonly Person[]).find((p) => p.id === id)?.display_name ??
      "A teammate");
