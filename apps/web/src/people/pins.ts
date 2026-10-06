// What S-28 shows of the pins, as pure functions over pinboard items (FR-PB-01, -02, -04, -05, -07).
// Who sees what is code, not a model (PE-01, PE-02): a personal pin is its person's alone, a team
// pin is read by the team only while it is active, and a proposed one only by whoever set it up.
import type { Mention, PinboardItem } from "@tilo/contracts";
import { SIGNED_IN, displayName } from "./data";

export type Kind = PinboardItem["kind"];
export type SortKey = "entry" | "due" | "updated";
export interface Sort {
  readonly key: SortKey;
  readonly dir: 1 | -1;
}

export const KIND_WORD: Readonly<Record<Kind, string>> = {
  note: "Note",
  decision: "Decision",
  deadline: "Deadline",
  link: "Link",
};

/** The team board as a member sees it: active entries, and the proposed ones they set up themselves.
 * Removed entries and a teammate's proposals are never shown (FR-PB-01, PE-02). */
export const teamBoard = (pins: readonly PinboardItem[], me = SIGNED_IN): PinboardItem[] =>
  pins.filter(
    (p) =>
      p.scope.kind === "team" &&
      (p.status === "active" || (p.status === "proposed" && p.set_up_by === me)),
  );

/** The person's own board: their personal pins and nobody else's (FR-PB-02, PE-01). */
export const personalBoard = (pins: readonly PinboardItem[], me = SIGNED_IN): PinboardItem[] =>
  pins.filter((p) => p.scope.kind === "personal" && p.scope.user === me && p.status === "active");

/** Edit is for the person who set an entry up, and for their own personal board (FR-PB-05). */
export const canEdit = (pin: PinboardItem, me = SIGNED_IN): boolean => pin.set_up_by === me;

/** The people tagged on a pin now: a removed tag is gone (FR-PB-04). Personal pins take none. */
export const taggedOn = (pin: PinboardItem, mentions: readonly Mention[]): string[] =>
  pin.scope.kind === "team"
    ? mentions.filter((m) => m.pin_id === pin.id && m.removed === null).map((m) => m.user)
    : [];

/** Rows in the order asked for. A missing due date goes last either way; ties fall to the id, so
 * the same pins always list the same way. */
export function sortPins(pins: readonly PinboardItem[], { key, dir }: Sort): PinboardItem[] {
  const cmp = (a: PinboardItem, b: PinboardItem): number => {
    if (key === "due") {
      if (a.due === null || b.due === null) return a.due === b.due ? 0 : a.due === null ? 1 : -1;
      return dir * a.due.localeCompare(b.due);
    }
    const [x, y] = key === "entry" ? [a.title, b.title] : [a.updated_at, b.updated_at];
    return dir * x.localeCompare(y);
  };
  return [...pins].sort((a, b) => cmp(a, b) || a.id.localeCompare(b.id));
}

const FROM = {
  meeting: "a meeting",
  mail: "a mail",
  call: "a call",
  request: "a request",
  manual: "a manual entry",
} as const;

/** "Added by Tilo from a meeting" for a Tilo-made pin, else who made it (PE-08). A meeting is named
 * by kind only: its title is the meeting owner's (PE-05). */
export function sourceLabel(pin: PinboardItem): string {
  if (pin.created_by.by === "tilo")
    return `Added by Tilo from ${FROM[pin.source?.kind ?? "manual"]}`;
  const by = pin.created_by.ref;
  return by === SIGNED_IN ? "Added by you" : `Added by ${displayName(by)}`;
}

/** The draft "Get in touch" starts with: to the set-up person only, by their display name (PE-09).
 * It is a draft: nothing is sent, and sending to another person is T3. */
export const draftFor = (pin: PinboardItem): string =>
  `Hi, a question about "${pin.title}" on the team pinboard. `;
