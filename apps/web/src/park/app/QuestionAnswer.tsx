import { useId, useState } from "react";
import type { Decision, DecisionKey } from "../api/types";

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
    <div style={{ width: "100%" }}>
      <div>
        {d.questionOptions.map((o) => (
          <button
            key={o.id}
            type="button"
            style={{ minHeight: 44, minWidth: 44 }}
            onClick={() => onDecide(d.k, undefined, o.id)}
          >
            {o.label}
          </button>
        ))}
      </div>
      <form
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
        <label htmlFor={id}>Type my own answer</label>
        <textarea
          id={id}
          value={text}
          maxLength={600}
          style={{ minHeight: 44, width: "100%" }}
          aria-invalid={Boolean(error)}
          onChange={(e) => setText(e.target.value)}
        />
        {error && <p role="alert">{error}</p>}
        <button type="submit" style={{ minHeight: 44, minWidth: 44 }}>
          Send
        </button>
      </form>
    </div>
  );
}
