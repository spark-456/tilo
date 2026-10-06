// Pieces S-26 and S-27 share. Neutral role tokens only: no design export covers these screens
// (design/source/INDEX.md), so they follow the pills of "Tilo Worlds" and the avatar and name rows
// of "Tilo Team" in the card, chip and row language of kit.tsx.
import type { ReactNode } from "react";
import { longDate, plural } from "../screens/kit";
import "./people.css";
import { QUOTES, displayName, personName } from "./data";

/** The quiet notice every fixture-backed screen carries, like the assistant panel's fixture adapter. */
export function PreviewNote({ what }: { what: string }) {
  return (
    <p className="people-preview" data-testid="people-preview">
      Preview, not connected. {what} is sample data and nothing you do here is saved.
    </p>
  );
}

/** "Priya Nair" -> "PN", "Dev from Acme" -> "DA": first and last word, upper case. */
export function initials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  const pick = [words[0], words.length > 1 ? words.at(-1) : undefined];
  return pick
    .map((w) => w?.[0] ?? "")
    .join("")
    .toUpperCase();
}

const SOURCE_PATH = {
  meeting: "M4 6h16v13H4zM4 10h16M8 3v4M16 3v4",
  mail: "M4 6h16v12H4zM4 7l8 6 8-6",
  you: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM5 20a7 7 0 0 1 14 0",
  guest: "M6 20V5h12v15M3 20h18M10 9h1M13 9h1M10 13h1M13 13h1",
} as const;

/** A small decorative glyph: where a work item came from (a meeting, mail, you), or the neutral
 * "guest" building. The words beside it say the same, so it is hidden from assistive tech. */
export function SourceIcon({ kind }: { kind: keyof typeof SOURCE_PATH }) {
  return (
    <svg
      className="source-icon"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={SOURCE_PATH[kind]} />
    </svg>
  );
}

/** A 28 px initials disc and a name, as Tilo Team shows people. Never an email or an id (ADR-0016).
 * `user` is a user id (shown as "You" for the signed-in person) or `name` is a name as typed.
 * `plain` is for an attendee with no account here: a neutral glyph, not initials, because a
 * company name ("Dev from Acme") would otherwise read as a person. */
export function PersonTag({
  user,
  name,
  plain,
}: { user?: string; name?: string; plain?: boolean }) {
  const full = user ? displayName(user) : (name ?? "");
  return (
    <span className="person-tag">
      <span className="avatar" aria-hidden="true">
        {plain ? <SourceIcon kind="guest" /> : initials(full)}
      </span>
      {user ? personName(user) : full}
    </span>
  );
}

/** "u0012" -> "line 12": the utterance id is internal, the line number is what a person can find. */
const lineOf = (id: string): string => `line ${Number.parseInt(id.slice(1), 10)}`;

/** The quotes behind an item, one per cited utterance, under a disclosure with a chevron that turns
 * when it opens. An item that cites nothing says so: it is never shown as backed (FR-MTG-04).
 * `meeting` keys the quotes. */
export function Evidence({ meeting, ids }: { meeting: string; ids: readonly string[] }) {
  if (ids.length === 0) return <span className="evidence-none">No evidence cited.</span>;
  return (
    <details className="evidence">
      <summary>
        <span className="chevron" aria-hidden="true" />
        Evidence ({plural(ids.length, "quote")})
      </summary>
      <ul>
        {ids.map((id) => {
          const q = QUOTES[meeting]?.[id];
          return (
            <li key={id}>
              {q ? <q>{q.text}</q> : "Quote not available."}
              <span className="evidence-by">
                {q ? `${q.speaker}, ` : ""}
                {lineOf(id)}
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

/** One strip pill: a word and its real count. */
export const pillLabel = (word: string, count: number): ReactNode => (
  <>
    {word} <b>{count}</b>
  </>
);

/** "2026-10-09" or a timestamp -> "9 Oct". */
export const shortDate = (when: string): string =>
  longDate(when.length === 10 ? `${when}T00:00:00Z` : when).replace(/ \d{4}$/, "");

/** A control that does nothing yet (apps/web/CLAUDE.md): visible, aria-disabled, "Coming soon". Its
 * name says what it acts on, so a column of them is not a column of the same word. */
export function SoonButton({ text, name }: { text: string; name: string }) {
  return (
    <button
      type="button"
      className="secondary placeholder compact"
      aria-disabled="true"
      aria-label={`${name}, coming soon`}
      title="Coming soon"
      onClick={(e) => e.preventDefault()}
    >
      {text}
    </button>
  );
}
