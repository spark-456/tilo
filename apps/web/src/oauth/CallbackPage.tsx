// ADR-0035 LC-02, LC-03 (FR-CON-02): /oauth/google/callback. Google sent the browser here with a one-time `code` and a
// `state`; `capture.ts` already took both out of the address bar. This page posts them once, only when the `state` is the
// one this tab saved before leaving (`ConnectFlow.finish`), then says plainly what happened and offers the way back to
// Connectors. It shows no code, no state and no Google text, loads no third-party asset and reads nothing but its props.
import { useEffect, useRef, useState } from "react";
import "../park/tokens/fonts";
import "../park/tokens/park.css";
import {
  type CallbackParams,
  type ConnectFlow,
  type FinishResult,
  RESULT_TEXT,
} from "../api/connect";
import "./callback.css";

type Shown = { kind: "working" } | FinishResult;

export default function CallbackPage({
  params,
  flow,
  back,
}: {
  readonly params: CallbackParams | null;
  readonly flow: () => ConnectFlow | null;
  readonly back: () => void;
}) {
  const [shown, setShown] = useState<Shown>({ kind: "working" });
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // one post, however often the effect runs
    started.current = true;
    const live = flow();
    if (params === null) setShown({ kind: "start_again" });
    else if (live === null) setShown({ kind: "unavailable" });
    else void live.finish(params).then(setShown, () => setShown({ kind: "unavailable" }));
  }, [flow, params]);
  const done = shown.kind !== "working";
  return (
    <div data-park data-time="day" className="oauth-root">
      <main className="oauth-main" data-testid="oauth-callback">
        <h1>
          {shown.kind === "working" ? "Finishing your Google sign-in" : RESULT_TEXT[shown.kind]}
        </h1>
        {shown.kind === "connected" ? (
          <>
            <p>Tilo can now use this access, and no more:</p>
            <ul>
              {shown.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </>
        ) : null}
        {shown.kind === "working" ? <p>One moment.</p> : null}
        {done ? (
          <button type="button" className="oauth-back" onClick={back}>
            Back to Connectors
          </button>
        ) : null}
      </main>
    </div>
  );
}
