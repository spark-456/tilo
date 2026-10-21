// WORLDS-MANAGE: the one confirm step before worlds leave the list. It names what goes ("Delete “K1 electric scooter”?"
// or "Delete 3 worlds?" with their names), says a world still at work is stopped first ("Stop and delete"), and that
// what was spent and recorded stays in the Ledger. A native <dialog> opened with showModal sits in the browser's top
// layer (above the nav and the Tilo bubble), keeps the page behind it inert and closes on Escape; focus goes back to
// what opened it. While the answer is out the buttons say so and take no second press.
import { type ReactNode, useEffect, useRef } from "react";
import type { World } from "../../api/types";
import { Button } from "../../components";
import { deleteSummary } from "./arrange";

const SHOWN = 6;
/** Pause is Pause all (FR-WLD-07): it also sets the person's autonomy rules back to Ask first. Said, never hidden. */
const PAUSE_NOTE = "Pausing also sets your autonomy rules back to Ask first.";

/** The sentence about worlds still at work, or nothing when none is. */
function workingLine(total: number, working: number): string {
  if (working === 0) return "";
  if (total === 1) return `It is still working: Tilo pauses it first. ${PAUSE_NOTE} `;
  if (working === total) return `They are still working: Tilo pauses them first. ${PAUSE_NOTE} `;
  return `${working} of them ${working === 1 ? "is" : "are"} still working: Tilo pauses ${working === 1 ? "it" : "those"} first. ${PAUSE_NOTE} `;
}

export function DeleteWorldsDialog({
  picked,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  picked: readonly World[];
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}): ReactNode {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return undefined;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try {
      if (!dialog.open) dialog.showModal();
    } catch {
      dialog.setAttribute("open", ""); // engines without showModal (test DOMs)
    }
    return () => {
      if (typeof dialog.close === "function" && dialog.open) dialog.close();
      opener?.focus?.();
    };
  }, []);
  const { title, working } = deleteSummary(picked);
  const names = picked.slice(0, SHOWN).map((w) => w.name);
  const more = picked.length - names.length;
  return (
    <dialog
      ref={ref}
      className="park-worlds-delete"
      aria-labelledby="park-worlds-delete-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) close.current();
      }}
    >
      <h2 id="park-worlds-delete-title" className="park-worlds-delete__title">
        {title}
      </h2>
      {picked.length > 1 ? (
        <ul className="park-worlds-delete__names">
          {names.map((n, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: names can repeat; the list is fixed while open
            <li key={i}>{n}</li>
          ))}
          {more > 0 ? <li>{`and ${more} more`}</li> : null}
        </ul>
      ) : null}
      <p className="park-worlds-delete__body">
        {workingLine(picked.length, working)}
        {picked.length === 1 ? "It leaves" : "They leave"} your Worlds list for good. What was spent
        and recorded stays in your Ledger.
      </p>
      {error ? (
        <p role="alert" className="park-worlds-delete__error">
          {error}
        </p>
      ) : null}
      <div className="park-worlds-delete__actions">
        <Button variant="secondary" onClick={() => close.current()} disabled={busy}>
          Keep {picked.length === 1 ? "it" : "them"}
        </Button>
        <Button variant="primary" onClick={onConfirm} disabled={busy}>
          {busy ? "Deleting…" : working > 0 ? "Stop and delete" : "Delete"}
        </Button>
      </div>
    </dialog>
  );
}
