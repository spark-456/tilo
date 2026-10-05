// Pieces S-26 and S-27 share. Neutral role tokens only: no design export covers these screens
// (design/source/INDEX.md), so they follow the card, chip and row language of kit.tsx.
import { plural } from "../screens/kit";
import "./people.css";
import { QUOTES } from "./data";

/** The quiet notice every fixture-backed screen carries, like the assistant panel's adapter. */
export function PreviewNote({ what }: { what: string }) {
  return (
    <p className="people-preview" data-testid="people-preview">
      Preview, not connected. {what} is sample data and nothing you do here is saved.
    </p>
  );
}

/** The quotes behind an item, one per cited utterance, under a disclosure. An item that cites
 * nothing says so: it is never shown as backed (FR-MTG-04). `meeting` keys the quotes. */
export function Evidence({ meeting, ids }: { meeting: string; ids: readonly string[] }) {
  if (ids.length === 0) return <span className="evidence-none">No evidence cited.</span>;
  return (
    <details className="evidence">
      <summary>Evidence ({plural(ids.length, "quote")})</summary>
      <ul>
        {ids.map((id) => {
          const q = QUOTES[meeting]?.[id];
          return (
            <li key={id}>
              {q ? <q>{q.text}</q> : "Quote not available."}
              <span className="evidence-by">
                {q ? `${q.speaker}, ` : ""}
                {id}
              </span>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
