// ADR-0035 L6c (FR-CON-02): the form of a needs-you card that asks the person for fields (its option `provide`): who a
// mail goes to, a subject, a file name, an event's times. One input per asked field, labelled from the API; a plain
// check before sending, the API's own plain reason after (422); disabled while sending. Typed values go to the one
// POST of `supplyCardFields` and are never kept, logged or shown again. Nothing here makes a value up.
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { type FieldSpec, type FieldsApi, fieldProblem } from "../api/fields";
import { describeError } from "../screens/remote";

type Load =
  | { kind: "loading" }
  | { kind: "ready"; specs: FieldSpec[] }
  | { kind: "failed"; message: string };

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
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const live = useRef(true);
  const group = useId();
  const refs = useRef<Record<string, HTMLInputElement | null>>({});

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the retry button
  useEffect(() => {
    let current = true;
    setLoad({ kind: "loading" });
    api.getCardFields(cardId).then(
      (specs) => current && setLoad({ kind: "ready", specs }),
      (e: unknown) =>
        current && setLoad({ kind: "failed", message: describeError("load what to add", e) }),
    );
    return () => {
      current = false;
    };
  }, [api, cardId, attempt]);

  const submit = useCallback(() => {
    if (load.kind !== "ready" || sending) return;
    const found: Record<string, string> = {};
    for (const spec of load.specs) {
      const problem = fieldProblem(spec, values[spec.name] ?? "");
      if (problem) found[spec.name] = problem;
    }
    setProblems(found);
    setRefusal(null);
    const first = load.specs.find((s) => found[s.name]);
    if (first) {
      refs.current[first.name]?.focus();
      return;
    }
    setSending(true);
    const body = Object.fromEntries(load.specs.map((s) => [s.name, (values[s.name] ?? "").trim()]));
    api.supplyCardFields(cardId, body).then(
      () => {
        if (!live.current) return;
        setSending(false);
        setSent(true);
      },
      (e: unknown) => {
        if (!live.current) return;
        setSending(false);
        setRefusal(describeError("add that", e));
      },
    );
  }, [api, cardId, load, sending, values]);

  if (load.kind === "loading") {
    return <output className="section-note">Loading what to add…</output>;
  }
  if (load.kind === "failed") {
    return (
      <div className="need-fields">
        <p className="need-error" role="alert">
          {load.message}
        </p>
        <button type="button" className="secondary" onClick={() => setAttempt((n) => n + 1)}>
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
        submit();
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
              ref={(el) => {
                refs.current[spec.name] = el;
              }}
              type="text"
              name={spec.name}
              value={values[spec.name] ?? ""}
              maxLength={spec.maxLength}
              required
              autoComplete="off"
              spellCheck={false}
              disabled={sending || sent}
              aria-invalid={problem ? "true" : undefined}
              aria-describedby={`${id}-hint${problem ? ` ${id}-error` : ""}`}
              onChange={(e) => setValues((v) => ({ ...v, [spec.name]: e.target.value }))}
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
