// ADR-0035 L6d (FR-CON-02): "Show me" on a gate sheet: the document the gate pins, read from the owner-only item
// route when the person asks, and drawn as text by `ItemDocumentView` (never markup). Nothing is fetched until the
// button is pressed; a refusal is a fixed sentence (the reply's own words are never shown). A READ: it answers nothing.
import { useId, useRef, useState } from "react";
import type { ItemApi, PinnedItem } from "../api/item";
import { ItemDocumentView } from "./ItemDocumentView";

type State =
  | { kind: "closed" }
  | { kind: "loading" }
  | { kind: "ready"; item: PinnedItem }
  | { kind: "failed" };

export function ShowItem({ api, cardId }: { api: ItemApi; cardId: string }) {
  const [state, setState] = useState<State>({ kind: "closed" });
  const region = useId();
  const latest = useRef(0);
  const open = () => {
    const mine = ++latest.current;
    setState({ kind: "loading" });
    api.getCardItem(cardId).then(
      (item) => latest.current === mine && setState({ kind: "ready", item }),
      () => latest.current === mine && setState({ kind: "failed" }),
    );
  };
  const shown = state.kind !== "closed";
  return (
    <div className="gate-show">
      <button
        type="button"
        className="secondary"
        aria-expanded={shown}
        aria-controls={region}
        disabled={state.kind === "loading"}
        onClick={() => {
          if (shown && state.kind !== "failed") {
            latest.current += 1;
            setState({ kind: "closed" });
          } else open();
        }}
      >
        {shown && state.kind !== "failed" ? "Hide it" : "Show me"}
      </button>
      <div id={region} aria-live="polite">
        {state.kind === "loading" && <output className="section-note">Loading the item…</output>}
        {state.kind === "failed" && (
          <p className="need-error" role="alert">
            This item cannot be shown right now. It is not sent unless you approve it.
          </p>
        )}
        {state.kind === "ready" && (
          <ItemDocumentView document={state.item.document} recipients={state.item.recipients} />
        )}
      </div>
    </div>
  );
}
