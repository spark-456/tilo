// SEC-15: the sign-up question, "visitor or Google AI Builder Cup judge?". An explicit choice (nothing is
// preselected), no password or other field: Tilo never handles passwords. The answer is a request the server
// stores once and enforces; this page only asks it.
import { useId, useState } from "react";
import { AccessScreen } from "./AccessScreen";

export type Declaration = "visitor" | "judge";

const CHOICES: ReadonlyArray<{ value: Declaration; label: string; detail: string }> = [
  {
    value: "visitor",
    label: "I am a visitor",
    detail:
      "Tilo is still under construction and is not open to the public yet. You will see a short notice for now.",
  },
  {
    value: "judge",
    label: "I am a Google AI Builder Cup judge",
    detail:
      "Full access to the product. Runs use recorded replay models unless the team switches live models on, and usage limits apply.",
  },
];

export function SignUpDeclaration({
  onSubmit,
  busy = false,
}: {
  readonly onSubmit: (declaration: Declaration) => void | Promise<void>;
  readonly busy?: boolean;
}) {
  const name = useId();
  const [choice, setChoice] = useState<Declaration | null>(null);
  return (
    <AccessScreen>
      <form
        data-testid="sign-up-declaration"
        onSubmit={(event) => {
          event.preventDefault();
          if (choice !== null && !busy) void onSubmit(choice);
        }}
      >
        <h1>One quick question</h1>
        <fieldset>
          <legend>Are you a visitor or a Google AI Builder Cup judge?</legend>
          {CHOICES.map(({ value, label, detail }) => (
            <label key={value} className="park-access__choice">
              <input
                type="radio"
                name={name}
                value={value}
                checked={choice === value}
                onChange={() => setChoice(value)}
              />
              <span>
                <strong>{label}</strong>
                <span>{detail}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <p>You choose once. It cannot be changed from this page.</p>
        <button
          type="submit"
          className="primary park-access__continue"
          disabled={choice === null || busy}
          aria-busy={busy || undefined}
        >
          Continue
        </button>
      </form>
    </AccessScreen>
  );
}
