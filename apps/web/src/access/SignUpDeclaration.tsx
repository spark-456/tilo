// SEC-15: the sign-up question, "visitor or Google AI Builder Cup judge?". An explicit choice (nothing is
// preselected), no password or other field: Tilo never handles passwords. The answer is a request the server
// stores once and enforces; this page only asks it.
import { useId, useState } from "react";

export type Declaration = "visitor" | "judge";

const CHOICES: ReadonlyArray<{ value: Declaration; label: string }> = [
  { value: "visitor", label: "I am a visitor" },
  { value: "judge", label: "I am a Google AI Builder Cup judge" },
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
    <form
      className="screen-body"
      data-testid="sign-up-declaration"
      onSubmit={(event) => {
        event.preventDefault();
        if (choice !== null && !busy) void onSubmit(choice);
      }}
    >
      <h1>Who is signing up?</h1>
      <fieldset>
        <legend>Are you a visitor or a Google AI Builder Cup judge?</legend>
        {CHOICES.map(({ value, label }) => (
          <label key={value}>
            <input
              type="radio"
              name={name}
              value={value}
              checked={choice === value}
              onChange={() => setChoice(value)}
            />{" "}
            {label}
          </label>
        ))}
      </fieldset>
      <button
        type="submit"
        className="primary"
        disabled={choice === null || busy}
        aria-busy={busy || undefined}
      >
        Continue
      </button>
    </form>
  );
}
