// FR-HIL-12: the page behind `/share/<token>`. A signed-in Approver sees the gate the owner shared and answers it
// once. The token is read from the address and used in two request paths only. The title and every sentence on
// the page are fixed words or the card's own: the token is never shown, linked or logged. No choice is made for the
// person (nothing is pre-selected, not even the suggested option) and the one answer is sent once, never retried.
import { useEffect, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { usePathname } from "../router";
import { Chip, Page } from "../screens/kit";
import {
  type GateView,
  REFUSAL_TEXT,
  type ShareHttp,
  type ShareRefusal,
  answerShare,
  openShare,
  tokenOf,
} from "./shareLink";

type State =
  | { step: "loading" }
  | { step: "open"; view: GateView }
  | { step: "sending"; view: GateView }
  | { step: "answered" }
  | { step: "refused"; refusal: ShareRefusal; view?: GateView };

const hasHttp = (c: unknown): c is ShareHttp =>
  typeof (c as Partial<ShareHttp> | null)?.getJson === "function" &&
  typeof (c as Partial<ShareHttp> | null)?.postJson === "function";

export function SharePage({
  http: given,
  token: givenToken,
}: { http?: ShareHttp; token?: string }) {
  const client = useClient();
  const path = usePathname();
  const http = given ?? (hasHttp(client) ? client : null);
  const token = givenToken ?? tokenOf(path);
  const [state, setState] = useState<State>({ step: "loading" });
  const [chosen, setChosen] = useState<string | null>(null);

  useEffect(() => {
    if (!http || !token) {
      setState({ step: "refused", refusal: "unavailable" });
      return undefined;
    }
    let live = true;
    openShare(http, token).then((r) => {
      if (!live) return;
      setState(
        "view" in r ? { step: "open", view: r.view } : { step: "refused", refusal: r.refusal },
      );
    });
    return () => {
      live = false;
    };
  }, [http, token]);

  const send = (view: GateView) => {
    if (!http || !token || !chosen) return;
    setState({ step: "sending", view });
    answerShare(http, token, chosen).then((r) =>
      setState(
        r === "answered"
          ? { step: "answered" }
          : // the card stays for a failure the person can try again; a link that no longer works shows only its line
            r === "unavailable" || r === "sign_in"
            ? { step: "refused", refusal: r }
            : { step: "refused", refusal: r, view },
      ),
    );
  };

  const view = "view" in state ? state.view : undefined;
  const picked = view?.options.find((o) => o.id === chosen);
  return (
    <Page
      testid="share-page"
      title="Approve a shared request"
      sub="Someone shared this with you to approve. Nothing happens until you choose."
    >
      {state.step === "loading" ? <output>Opening…</output> : null}
      {state.step === "answered" ? (
        <output data-testid="share-answered">Your answer was recorded.</output>
      ) : null}
      {state.step === "refused" ? (
        <output aria-live="assertive" data-testid="share-refused">
          {REFUSAL_TEXT[state.refusal]}
        </output>
      ) : null}
      {view && state.step !== "answered" ? (
        <section aria-label="Shared request" className="need-card">
          <p className="need-what">{view.what}</p>
          <p className="section-note">{view.why}</p>
          <p data-testid="share-action">{view.action}</p>
          {view.recipients.length > 0 ? (
            <p className="section-note">{`Goes to: ${view.recipients.join(", ")}`}</p>
          ) : null}
          {view.irreversible ? <p className="section-note">This cannot be undone.</p> : null}
          <fieldset className="need-options" disabled={state.step === "sending"}>
            <legend>Your answer</legend>
            {view.options.map((o) => (
              <label key={o.id} className="need-option">
                <input
                  type="radio"
                  name="share-option"
                  checked={chosen === o.id}
                  onChange={() => setChosen(o.id)}
                />
                <span className="need-option-text">
                  <b>{o.label}</b>
                  {o.suggested ? <Chip tone="suggested">Suggested</Chip> : null}
                </span>
              </label>
            ))}
          </fieldset>
          <button
            type="button"
            className="primary"
            disabled={!picked || state.step === "sending"}
            aria-busy={state.step === "sending" ? "true" : undefined}
            onClick={() => send(view)}
          >
            {picked?.label ?? "Choose an option"}
          </button>
        </section>
      ) : null}
    </Page>
  );
}
