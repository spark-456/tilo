// FR-HIL-12: the page behind `/share/<token>`. A signed-in Approver sees the gate the owner shared and answers it
// once. The token is read from the address and used in two request paths only. The title and every sentence on
// the page are fixed words or the card's own: the token is never shown, linked or logged. No choice is made for the
// person (nothing is pre-selected, not even the suggested option) and the one answer is sent once, never retried.
// The page holds one link: a new token is a new page (keyed), so a card or a choice never carries over to it.
import { useEffect, useRef, useState } from "react";
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
  | { step: "answered"; said: string }
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
  return <ShareGate key={token ?? ""} http={http} token={token} />;
}

function ShareGate({ http, token }: { http: ShareHttp | null; token: string | null }) {
  const [state, setState] = useState<State>({ step: "loading" });
  const [chosen, setChosen] = useState<string | null>(null);
  const sending = useRef(false);

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
    if (!http || !token || !chosen || sending.current) return;
    sending.current = true;
    const option = view.options.find((o) => o.id === chosen);
    setState({ step: "sending", view });
    answerShare(http, token, chosen).then((r) => {
      sending.current = false;
      if (r === "answered") {
        // Hold and Edit first write nothing on the server: say what happened, not "recorded".
        const label = option?.label ?? "your answer";
        setState({
          step: "answered",
          said:
            option?.id === "approve"
              ? "Your approval was recorded."
              : `You chose “${label}”. Nothing was sent.`,
        });
      } else if (r === "unavailable" || r === "sign_in") {
        setState({ step: "refused", refusal: r }); // a link that no longer works shows only its line
      } else {
        setState({ step: "refused", refusal: r, view }); // the card stays; nothing is resent by itself
      }
    });
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
        <output data-testid="share-answered">{state.said}</output>
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
          <dl className="gate-facts" data-testid="share-facts">
            <div>
              <dt>The exact action</dt>
              <dd data-testid="share-action">{view.action}</dd>
            </div>
            <div>
              <dt>Who receives it</dt>
              <dd>
                {view.recipients.length > 0
                  ? view.recipients.join(", ")
                  : "No one: nothing leaves your own Drive."}
              </dd>
            </div>
            {view.item ? (
              <div>
                <dt>What it holds</dt>
                <dd>{view.item}</dd>
              </div>
            ) : null}
            <div>
              <dt>Can it be undone?</dt>
              <dd>
                {view.irreversible
                  ? "Once done, it can't be undone."
                  : "Yes, you can undo it afterwards."}
              </dd>
            </div>
            {view.tier ? (
              <div>
                <dt>Risk tier</dt>
                <dd>{view.tier === "T3" ? "T3: a person always decides this." : view.tier}</dd>
              </div>
            ) : null}
          </dl>
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
          <p className="section-note">
            Only approving sends anything. Choosing another option, such as Hold or Edit first,
            sends nothing from this page.
          </p>
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
