// WORLD-USEFUL: reads the run's delivered output once it is recorded as delivered, so the page can show it.
// One read per world (the owner route, GET /worlds/{id}/result); text is decoded here, anything else stays a file.
import { useEffect, useState } from "react";
import type { Api } from "../../api";
import { hasResultReader, readResult } from "../../api/results";

/** The most text drawn on the page; the file itself always has all of it. */
export const SHOWN_CHARS = 200_000;

export type ResultView =
  | { readonly status: "off" }
  | { readonly status: "loading" }
  | { readonly status: "error" }
  | { readonly status: "file"; readonly blob: Blob }
  | {
      readonly status: "text";
      readonly blob: Blob;
      readonly kind: "markdown" | "json" | "plain";
      readonly text: string;
      readonly cut: boolean;
    };

function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

export function useRunResult(
  api: Api,
  worldId: string,
  ready: boolean,
  attempt: number,
): ResultView {
  const [view, setView] = useState<ResultView>({ status: "off" });
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the caller's retry: a new value reads again
  useEffect(() => {
    if (!ready) {
      setView({ status: "off" });
      return undefined;
    }
    if (!hasResultReader(api)) {
      setView({ status: "error" });
      return undefined;
    }
    let live = true;
    setView({ status: "loading" });
    const gone = () => live && setView({ status: "error" });
    readResult(api, worldId)
      .then(async (blob) => {
        const type = blob.type.split(";")[0]?.trim() ?? "";
        if (!live) return;
        if (type === "text/markdown" || type === "text/plain" || type === "application/json") {
          const raw = await blob.text();
          const text = type === "application/json" ? prettyJson(raw) : raw;
          if (live)
            setView({
              status: "text",
              blob,
              text: text.slice(0, SHOWN_CHARS),
              cut: text.length > SHOWN_CHARS,
              kind:
                type === "text/markdown"
                  ? "markdown"
                  : type === "application/json"
                    ? "json"
                    : "plain",
            });
        } else setView({ status: "file", blob });
      })
      .catch(gone);
    return () => {
      live = false;
    };
  }, [api, worldId, ready, attempt]);
  return view;
}
