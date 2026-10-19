// ADR-0035 L6d (FR-CON-02): the state of a fields form, with no markup, so the Needs-you card and the Park Decisions
// card answer a `provide` card the same way (Park may import only `src/api`). It loads what is asked, checks the
// typed values before sending, sends them to the one POST and keeps the API's own plain reason. Typed values stay in
// this hook's state: never stored, logged or shown again. Nothing here makes a value up.
import { useCallback, useEffect, useRef, useState } from "react";
import { describeError } from "./describeError";
import { type FieldSpec, type FieldsApi, fieldProblem } from "./fields";

export type FieldsLoad =
  | { kind: "loading" }
  | { kind: "ready"; specs: FieldSpec[] }
  | { kind: "failed"; message: string };

export function useFieldsForm(api: FieldsApi, cardId: string) {
  const [load, setLoad] = useState<FieldsLoad>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const live = useRef(true);
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

  return {
    load,
    values,
    problems,
    sending,
    refusal,
    sent,
    submit,
    retry: () => setAttempt((n) => n + 1),
    setValue: (name: string, value: string) => setValues((v) => ({ ...v, [name]: value })),
    register: (name: string) => (el: HTMLInputElement | null) => {
      refs.current[name] = el;
    },
  };
}
