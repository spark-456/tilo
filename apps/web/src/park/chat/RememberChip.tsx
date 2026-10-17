import type { MemoryItemSuggestion } from "@tilo/contracts";
import { useMemo, useState } from "react";
import { memoryApi } from "../api/live/memory";
import { useWorldClient } from "../app/context";

export function RememberChip({ suggestion }: { suggestion: MemoryItemSuggestion | undefined }) {
  const client = useWorldClient();
  const api = useMemo(() => client && memoryApi(client), [client]);
  const [state, setState] = useState<"offered" | "saving" | "saved" | "dismissed" | "error">(
    "offered",
  );
  if (!suggestion || !api || state === "dismissed") return null;
  const remember = async () => {
    if (state === "saving" || state === "saved") return;
    setState("saving");
    try {
      await api.create({ ...suggestion, source: "tilo_suggested" });
      setState("saved");
    } catch {
      setState("error");
    }
  };
  return (
    <span className="park-remember-chip">
      <span>Remember “{suggestion.text}”?</span>{" "}
      {state === "saved" ? (
        <output>Saved</output>
      ) : (
        <>
          <button type="button" disabled={state === "saving"} onClick={() => void remember()}>
            {state === "saving" ? "Saving…" : "Remember"}
          </button>{" "}
          <button type="button" disabled={state === "saving"} onClick={() => setState("dismissed")}>
            Not now
          </button>
          {state === "error" ? <span role="alert">Could not save this memory.</span> : null}
        </>
      )}
    </span>
  );
}
