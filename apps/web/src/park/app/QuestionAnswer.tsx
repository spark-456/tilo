import { useId, useState } from "react";
import type { Decision, DecisionKey } from "../api/types";
import "../studio/studio.components.css";

export function QuestionAnswer({
  d,
  onDecide,
}: {
  d: Decision;
  onDecide: (key: DecisionKey, text?: string, option?: string) => void;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  if (!d.questionOptions) return null;
  return (
    <div className="park-question">
      <div className="park-question__options">
        {d.questionOptions.map((o) => (
          <button
            key={o.id}
            type="button"
            className="park-question__option"
            style={{ minHeight: 44, minWidth: 44 }}
            onClick={() => onDecide(d.k, undefined, o.id)}
          >
            {o.label}
          </button>
        ))}
      </div>
      <form
        className="park-question__own"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim() || Array.from(text).length > 300) {
            setError("Type an answer using 1 to 300 characters.");
            return;
          }
          setError("");
          onDecide(d.k, text);
        }}
      >
        <label htmlFor={id} className="park-question__label">
          Type my own answer
        </label>
        <textarea
          id={id}
          value={text}
          maxLength={600}
          className="park-question__field"
          style={{ minHeight: 44, width: "100%" }}
          aria-invalid={Boolean(error)}
          onChange={(e) => setText(e.target.value)}
        />
        {error && (
          <p role="alert" className="park-question__error">
            {error}
          </p>
        )}
        <button
          type="submit"
          className="park-question__send"
          style={{ minHeight: 44, minWidth: 44 }}
        >
          Send
        </button>
      </form>
    </div>
  );
}
