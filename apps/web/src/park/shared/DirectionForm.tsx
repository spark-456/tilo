import { type FormEvent, useState } from "react";

export function DirectionForm({
  onStart,
  onCancel,
}: {
  onStart: (instruction: string) => Promise<void>;
  onCancel?: (() => void) | undefined;
}) {
  const [instruction, setInstruction] = useState("");
  const [state, setState] = useState<"idle" | "starting" | "started" | "failed">("idle");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || state === "starting" || state === "started") return;
    setState("starting");
    void onStart(text).then(
      () => setState("started"),
      () => setState("failed"),
    );
  };

  return (
    <form className="tw-direction" onSubmit={submit}>
      <label>
        <strong>Change direction</strong>
        <span>Start a new run with this world’s brief and completed steps.</span>
        <textarea
          value={instruction}
          maxLength={2000}
          aria-label="What should the team change?"
          placeholder="Keep what worked, then tell the team what to change"
          onChange={(event) => setInstruction(event.target.value)}
        />
      </label>
      {state === "failed" ? <p role="alert">The new run could not start. Try again.</p> : null}
      {state === "started" ? <output>New run started.</output> : null}
      <div className="tw-direction__actions">
        <button
          type="submit"
          disabled={!instruction.trim() || state === "starting" || state === "started"}
        >
          {state === "starting"
            ? "Starting new run…"
            : state === "started"
              ? "New run started"
              : "Start new run"}
        </button>
        {onCancel ? (
          <button type="button" className="tw-room__quiet" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}
