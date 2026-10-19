// SEC-16 / BQ-FEEDBACK-1 (user request, 8 Oct 2026; not in the PRD): shown when the server refuses new live work at
// the person's lifetime allowance. It says the allowance is used up (never an amount, a code or the server's words),
// and offers a feedback box. "Thanks" appears only after `submit` resolves, i.e. after the server confirmed (HR-1);
// a failure keeps the text and says so. Shared by the Park shell and the flow screens, so neither imports the other.
// No timer, no animation; plain role tokens only.
import { useEffect, useId, useRef, useState } from "react";
import "./LifetimeCapDialog.css";

const MAX_CHARS = 2000;

export function LifetimeCapDialog({
  submit,
  onClose,
}: { submit: (words: string) => Promise<void>; onClose: () => void }) {
  const titleId = useId();
  const areaId = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  const alive = useRef(true);
  const sending = useRef(false);
  const [words, setWords] = useState("");
  const [phase, setPhase] = useState<"idle" | "sending" | "failed" | "sent">("idle");

  useEffect(() => {
    alive.current = true;
    area.current?.focus();
    return () => {
      alive.current = false;
    };
  }, []);

  const send = () => {
    if (sending.current || words.trim() === "") return;
    sending.current = true;
    setPhase("sending");
    Promise.resolve()
      .then(() => submit(words))
      .then(
        () => alive.current && setPhase("sent"),
        () => alive.current && setPhase("failed"),
      )
      .finally(() => {
        sending.current = false;
      });
  };

  return (
    <div className="lifetime-cap-backdrop">
      <div
        className="lifetime-cap"
        // biome-ignore lint/a11y/useSemanticElements: a modal named by its title; Escape closes it.
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <h2 id={titleId} className="lifetime-cap-title">
          Beta allowance used
        </h2>
        <p>You have used your beta allowance for live models.</p>
        <p>New plans and subscriptions come after beta testing ends.</p>
        <p>If you liked Tilo, you can help by giving honest feedback and critique.</p>
        {phase === "sent" ? (
          // biome-ignore lint/a11y/useSemanticElements: a result line announced once, as the replay banner is.
          <p role="status" className="lifetime-cap-thanks">
            Thanks. Your feedback was received.
          </p>
        ) : (
          <>
            <label htmlFor={areaId} className="lifetime-cap-label">
              Your feedback
            </label>
            <textarea
              id={areaId}
              ref={area}
              className="lifetime-cap-area"
              rows={5}
              maxLength={MAX_CHARS}
              value={words}
              onChange={(e) => setWords(e.target.value)}
            />
            {phase === "failed" && (
              <p role="alert" className="lifetime-cap-error">
                Your feedback was not sent. Your text is still here, so you can try again.
              </p>
            )}
          </>
        )}
        <div className="lifetime-cap-actions">
          {phase !== "sent" && (
            <button
              type="button"
              className="secondary"
              disabled={phase === "sending" || words.trim() === ""}
              aria-busy={phase === "sending" ? "true" : undefined}
              onClick={send}
            >
              {phase === "sending" ? "Sending…" : "Send feedback"}
            </button>
          )}
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
