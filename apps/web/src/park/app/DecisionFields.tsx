// ADR-0035 L6d (FR-CON-02): a `provide` decision (a card that asks for fields) is answered here, by typing them, never
// by a tap: one labelled input per asked field, a plain check before sending, the API's own plain reason after (422,
// announced), the first problem focused. The state is the shared `api/useFieldsForm`; Park tokens only.
import { useId, useMemo } from "react";
import type { FieldsApi } from "../../api/fields";
import { useFieldsForm } from "../../api/useFieldsForm";
import type { Decision } from "../api/types";
import { Button } from "../components";
import { useFieldsFor } from "./fieldsContext";
import "./DecisionFields.css";

export function DecisionFields({ d }: { d: Decision }) {
  const forWorld = useFieldsFor();
  const api = useMemo(() => forWorld?.(d.world) ?? null, [forWorld, d.world]);
  if (!api || !d.provide) return null;
  return <Form api={api} cardId={d.provide.cardId} />;
}

function Form({ api, cardId }: { api: FieldsApi; cardId: string }) {
  const form = useFieldsForm(api, cardId);
  const group = useId();
  const { load, sending, sent, refusal, problems } = form;
  if (load.kind === "loading")
    return <output className="park-provide__note">Loading what to add…</output>;
  if (load.kind === "failed")
    return (
      <div className="park-provide">
        <p className="park-provide__error" role="alert">
          {load.message}
        </p>
        <Button variant="secondary" size="sm" onClick={form.retry}>
          Try again
        </Button>
      </div>
    );
  return (
    <form
      className="park-provide"
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
          <div key={spec.name} className="park-provide__field">
            <label className="park-provide__label" htmlFor={id}>
              {spec.label}
            </label>
            <input
              id={id}
              ref={form.register(spec.name)}
              className="park-provide__input"
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
            <span id={`${id}-hint`} className="park-provide__hint">
              {spec.hint}
            </span>
            {problem && (
              <span id={`${id}-error`} className="park-provide__error" role="alert">
                {problem}
              </span>
            )}
          </div>
        );
      })}
      {refusal && (
        <p className="park-provide__error" role="alert">
          {refusal}
        </p>
      )}
      <Button
        variant="needs"
        size="sm"
        type="submit"
        disabled={sending || sent}
        aria-busy={sending ? "true" : undefined}
      >
        {sending ? "Sending…" : "Add details"}
      </Button>
      <output className="park-provide__note">
        {sent && "Added. Waiting for the item to come back for your approval…"}
      </output>
    </form>
  );
}
