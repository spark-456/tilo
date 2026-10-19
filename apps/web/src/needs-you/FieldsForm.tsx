// ADR-0035 L6c (FR-CON-02): the form of a needs-you card that asks the person for fields (its option `provide`): who a
// mail goes to, a subject, a file name, an event's times. One input per asked field, labelled from the API; a plain
// check before sending, the API's own plain reason after (422); disabled while sending. Typed values go to the one
// POST of `supplyCardFields` and are never kept, logged or shown again. Nothing here makes a value up. The state is
// `api/useFieldsForm` (the Park Decisions card shares it).
import { useId } from "react";
import type { FieldsApi } from "../api/fields";
import { useFieldsForm } from "../api/useFieldsForm";

export function FieldsForm({
  api,
  cardId,
  onHold,
}: {
  api: FieldsApi;
  cardId: string;
  /** The card's quiet Hold option, when it has one: asking for nothing is always allowed. */
  onHold?: (() => void) | undefined;
}) {
  const form = useFieldsForm(api, cardId);
  const group = useId();
  const { load, sending, sent, refusal, problems } = form;
  if (load.kind === "loading") {
    return <output className="section-note">Loading what to add…</output>;
  }
  if (load.kind === "failed") {
    return (
      <div className="need-fields">
        <p className="need-error" role="alert">
          {load.message}
        </p>
        <button type="button" className="secondary" onClick={form.retry}>
          Try again
        </button>
      </div>
    );
  }
  return (
    <form
      className="need-fields"
      aria-label="What to add"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        form.submit();
      }}
    >
      {load.specs.map((spec) => {
        const id = `${group}-${spec.name}`;
        const problem = problems[spec.name];
        return (
          <div key={spec.name} className="need-field">
            <label htmlFor={id}>{spec.label}</label>
            <input
              id={id}
              ref={form.register(spec.name)}
              type="text"
              name={spec.name}
              value={form.values[spec.name] ?? ""}
              maxLength={spec.maxLength}
              required
              autoComplete="off"
              spellCheck={false}
              disabled={sending || sent}
              aria-invalid={problem ? "true" : undefined}
              aria-describedby={`${id}-hint${problem ? ` ${id}-error` : ""}`}
              onChange={(e) => form.setValue(spec.name, e.target.value)}
            />
            <span id={`${id}-hint`} className="section-note">
              {spec.hint}
            </span>
            {problem && (
              <span id={`${id}-error`} className="need-error" role="alert">
                {problem}
              </span>
            )}
          </div>
        );
      })}
      {refusal && (
        <p className="need-error" role="alert">
          {refusal}
        </p>
      )}
      <div className="need-actions">
        <button
          type="submit"
          className="primary"
          disabled={sending || sent}
          aria-busy={sending ? "true" : undefined}
        >
          {sending ? "Adding…" : "Add it"}
        </button>
        {onHold && (
          <button type="button" className="secondary" disabled={sending || sent} onClick={onHold}>
            Hold
          </button>
        )}
      </div>
      <output className="need-status">
        {sent && "Added. Waiting for the item to come back for your approval…"}
      </output>
    </form>
  );
}
