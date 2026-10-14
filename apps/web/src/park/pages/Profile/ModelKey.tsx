// ADR-0041 (BYOK-5, INERT, SECURITY-FLAGGED: credential input): "Organisation model key" in Plan and billing, where
// the org's spend is. The org owner adds, replaces or removes the one key; every member reads only where work goes
// (BK-20). Honest states: off in this build (503 `not_configured`, while `config/byok.yaml` has `enabled: false`: the
// form is shown disabled), loading, failed with retry, signed out, not the owner, a demo needing a real sign-in.
// "Saved" shows only after the live answer and a re-read (`api/modelKey.ts`). The key lives in one controlled field,
// is cleared at the click, is never stored, put in a URL, logged or shown, and the server's own text is never shown.
import { useEffect, useMemo, useState } from "react";
import type {
  ModelKeyFlow,
  ModelKeyProblem,
  ModelKeyResult,
  ModelKeyView,
} from "../../../api/modelKey";
import { liveModelKeyFlow } from "../../../api/modelKeyEnv";
import { StatusChip } from "../../components";

// BK-06 (ADR-0041): shown before the field. `CONSENT_VERSION` is the version of exactly the words below: it is bumped
// with them, sent in the PUT body, and the server compares it with its own (a stale page is a 422 `confirm_required`).
// It is never taken from the server's answer: an echo would always match and no stale page could be seen (B6).
export const CONSENT_VERSION = 1;
const CONSENT =
  "This organisation's prompts, documents and answers will be sent to the provider you name, under that provider's terms. They may be processed outside asia-southeast1, and that provider's own logs may show them to the administrators of that account. Tilo's spending caps do not apply to this spend, and your organisation carries the provider's bill.";
const REMOVE_HELP =
  "Work will use Tilo's own key again. Revoke the key at the provider as well: a call already running may finish.";
const PROBLEMS: Record<ModelKeyProblem, string> = {
  not_configured:
    "Off in this build. This organisation's work uses Tilo's own model key, and nothing here can be saved.",
  sign_in: "Sign in to see or change this organisation's model key.",
  reauth:
    "For safety, adding or replacing a key needs a sign-in from the last 10 minutes. Sign out from the account menu, sign in again, then add the key.",
  owner_only: "Only this organisation's owner can see or change its model key.",
  under_construction: "Access to Tilo is not available for this account yet.",
  declaration_required: "Complete the sign-up question before using Tilo.",
  key_refused: "That key or project id was refused. Check it and try again. Nothing was saved.",
  confirm:
    "The consent wording has changed. Reload this page, read it again and confirm. Nothing was saved.",
  invalid: "A value was not accepted: check the bundle id and the daily limit. Nothing was saved.",
  rate_limited: "Too many key changes this hour. Try again later. Nothing was saved.",
  unavailable: "Tilo could not confirm this. Check the key's status above before trying again.",
  unconfirmed:
    "Tilo could not read the change back to confirm it. Reload to check the key's status before trying again.",
};
const STATUS: Record<string, string> = {
  none: "No key is set. This organisation's work uses Tilo's own model key.",
  unverified: "Saved, but the provider has not confirmed it yet. Work that needs it waits.",
  paused: "Paused. Work that needs this key waits.",
  invalid: "The provider refused this key. Replace it, or remove it.",
};
const OWN = "This organisation's work uses Tilo's own model key.";

/** The mask is CSS (`.park-profile-secret`, never a password field). A browser without it shows the field's text. */
function canMask(): boolean {
  return (
    typeof CSS !== "undefined" &&
    typeof CSS.supports === "function" &&
    CSS.supports("-webkit-text-security", "disc")
  );
}

function statusLine(v: ModelKeyView): string {
  if (!v.owner) {
    return v.active
      ? `This organisation's work uses its own model key (${v.label ?? "named by the owner"}).`
      : OWN;
  }
  if (v.state === "active" && !v.active) {
    // SEC-REVIEW-29 B7: the stored key is verified but the API says it is not in use: follow `active`, say why.
    return v.lastError === "not_configured"
      ? `Not in use. This key's bundle is no longer configured in this build, so work that needs it is refused, or runs on Tilo's own key only if you allowed that. Replace the key or remove it.`
      : `Not in use right now${v.lastError ? ` (${v.lastError})` : ""}. Work for this organisation does not use this key.`;
  }
  if (v.state === "active") {
    const added = v.setAt ? `, added ${v.setAt.slice(0, 10)}` : "";
    return `Active. Work for this organisation uses its own key (${v.label ?? "unnamed"}), version ${v.version ?? "?"}${added}.`;
  }
  return STATUS[v.state ?? "none"] ?? OWN;
}

type Remote =
  | { kind: "loading" }
  | { kind: "view"; view: ModelKeyView }
  | { kind: "problem"; problem: ModelKeyProblem };

function Body({ flow }: { flow: ModelKeyFlow }) {
  const [remote, setRemote] = useState<Remote>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [bundle, setBundle] = useState("");
  const [key, setKey] = useState("");
  const [project, setProject] = useState("");
  const [cap, setCap] = useState("");
  const [fallback, setFallback] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ModelKeyProblem | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the Try again signal
  useEffect(() => {
    let live = true;
    setRemote({ kind: "loading" });
    flow.read().then((r) => {
      if (live)
        setRemote(r.ok ? { kind: "view", view: r.view } : { kind: "problem", problem: r.problem });
    });
    return () => {
      live = false;
    };
  }, [flow, attempt]);

  if (remote.kind === "loading") {
    return <output className="park-profile-note">Loading the model key settings…</output>;
  }
  const off = remote.kind === "problem" && remote.problem === "not_configured";
  if (remote.kind === "problem" && !off) {
    const retry = remote.problem === "unavailable";
    return (
      <>
        <p
          role={retry ? "alert" : undefined}
          className={retry ? "park-profile-alert" : "park-profile-note"}
        >
          {retry
            ? "Tilo could not read the model key settings. Nothing was changed."
            : PROBLEMS[remote.problem]}
        </p>
        {retry ? (
          <button
            type="button"
            className="park-profile-small"
            onClick={() => setAttempt(attempt + 1)}
          >
            Try again
          </button>
        ) : null}
      </>
    );
  }
  // Off in this build: the same form, disabled, so nothing pretends to save. The API refuses before it looks at who
  // asks, so a member sees it too; a member's own answer (`{active, label}`) has no form.
  const view = remote.kind === "view" ? remote.view : null;
  const has = view?.owner === true && view.state !== "none";
  // The server's text is newer than the words on this page: nothing is sent until the page is reloaded. The owner's
  // answer carries the version the next widening act must confirm (the config's current one, org_model_key
  // owner_view), held key or not, so a bump locks an old page; a number older than the page's never locks.
  const stale = view?.owner === true && (view.consentVersion ?? 0) > CONSENT_VERSION;
  const days = Number(cap);
  const ready =
    view?.owner === true &&
    view.consentVersion !== null &&
    !stale &&
    agreed &&
    bundle.trim() !== "" &&
    (key !== "") !== (project.trim() !== "") &&
    Number.isInteger(days) &&
    days >= 1 &&
    !busy;
  const after = (r: ModelKeyResult, doneText: string) => {
    if (r.ok) {
      setRemote({ kind: "view", view: r.view });
      setDone(doneText);
      setAgreed(false);
    } else if (r.problem === "not_configured" || r.problem === "sign_in") {
      setRemote({ kind: "problem", problem: r.problem });
    } else setProblem(r.problem);
    setBusy(false);
  };
  const save = async () => {
    if (!ready || !view) return;
    const typed = key;
    setKey(""); // gone from the field at the click, whatever the answer
    setBusy(true);
    setProblem(null);
    setDone(null);
    after(
      await flow.save({
        bundleId: bundle.trim(),
        key: typed === "" ? null : typed,
        projectId: project.trim() === "" ? null : project.trim(),
        dayCapCredits: days,
        fallbackToTilo: fallback,
        consentVersion: CONSENT_VERSION,
      }),
      "Key saved and confirmed. It cannot be shown again.",
    );
  };
  const remove = async () => {
    setConfirmRemove(false);
    setBusy(true);
    setProblem(null);
    setDone(null);
    after(await flow.remove(), "Key removed. This organisation's work uses Tilo's own key again.");
  };

  return (
    <>
      <div className="park-profile-quiet">
        <div className="park-profile-grow" aria-live="polite">
          <div className="park-profile-msub">
            {view ? statusLine(view) : PROBLEMS.not_configured}
          </div>
        </div>
        {view?.owner ? (
          <StatusChip
            tone={
              view.state === "active" && view.active
                ? "ok"
                : view.state === "none"
                  ? "neutral"
                  : "amber"
            }
          >
            {view.state === "none"
              ? "Not set"
              : view.state === "active" && !view.active
                ? "not in use"
                : view.state}
          </StatusChip>
        ) : null}
      </div>
      {problem || stale ? (
        <p role="alert" className="park-profile-alert">
          {PROBLEMS[problem ?? "confirm"]}
        </p>
      ) : null}
      {done ? <output className="park-profile-note">{done}</output> : null}
      {off || view?.owner ? (
        <form
          autoComplete="off"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <fieldset className="park-profile-mkset" disabled={off || busy}>
            <legend className="park-profile-group">{has ? "Replace the key" : "Add a key"}</legend>
            <p className="park-profile-note">{CONSENT}</p>
            <div className="park-profile-form">
              <label className="park-profile-field">
                <span className="park-profile-label">Bundle id</span>
                <input
                  className="park-profile-input"
                  type="text"
                  value={bundle}
                  maxLength={64}
                  autoComplete="off"
                  onChange={(e) => setBundle(e.target.value)}
                />
                <span className="park-profile-help">
                  The id of the provider bundle your Tilo operator set up.
                </span>
              </label>
              <label className="park-profile-field">
                <span className="park-profile-label">API key</span>
                {/* PRD 16.1 rule 1: no password field. A text field masked by CSS, with every
                    password-manager and autofill hint off, so a browser never offers to save the key (B5). */}
                <input
                  className="park-profile-input park-profile-secret"
                  type="text"
                  name="provider-api-token"
                  value={key}
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-1p-ignore
                  data-lpignore="true"
                  data-bwignore="true"
                  data-form-type="other"
                  onChange={(e) => setKey(e.target.value)}
                />
                <span className="park-profile-help">
                  Sent once and kept in Tilo's vault. It is never shown again.
                  {canMask()
                    ? ""
                    : " This browser cannot hide what you type here, so check that no one can see your screen."}
                </span>
              </label>
              <label className="park-profile-field">
                <span className="park-profile-label">Vertex project id (instead of a key)</span>
                <input
                  className="park-profile-input"
                  type="text"
                  value={project}
                  maxLength={64}
                  autoComplete="off"
                  onChange={(e) => setProject(e.target.value)}
                />
                <span className="park-profile-help">
                  Only for a Vertex bundle that uses your own project. Give a key or a project id,
                  not both.
                </span>
              </label>
              <label className="park-profile-field">
                <span className="park-profile-label">Daily limit (credits)</span>
                <input
                  className="park-profile-input"
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={cap}
                  autoComplete="off"
                  onChange={(e) => setCap(e.target.value)}
                />
                <span className="park-profile-help">
                  The most this organisation's own key may spend in a day.
                </span>
              </label>
            </div>
            <label className="park-profile-check">
              <input
                type="checkbox"
                checked={fallback}
                onChange={(e) => setFallback(e.target.checked)}
              />
              If this key stops working, let Tilo's own key take over
            </label>
            <label className="park-profile-check">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
              />
              I have read the above and confirm this change
            </label>
            <div className="park-profile-foot">
              {has ? (
                <button
                  type="button"
                  className="park-profile-btn park-profile-btn--quiet"
                  onClick={() => setConfirmRemove(true)}
                >
                  Remove key
                </button>
              ) : null}
              <button
                type="submit"
                className="park-profile-btn park-profile-btn--quiet"
                disabled={!ready}
                aria-busy={busy}
              >
                {busy ? "Saving…" : "Save key"}
              </button>
            </div>
          </fieldset>
        </form>
      ) : null}
      {confirmRemove ? (
        <section
          role="alertdialog"
          aria-label="Confirm removing the model key"
          className="park-profile-session"
          onKeyDown={(e) => e.key === "Escape" && setConfirmRemove(false)}
        >
          <div className="park-profile-grow">
            <div className="park-profile-stitle">Remove this organisation's model key?</div>
            <div className="park-profile-ssub">{REMOVE_HELP}</div>
          </div>
          <button
            type="button"
            className="park-profile-signout"
            onClick={() => setConfirmRemove(false)}
          >
            Cancel
          </button>
          <button type="button" className="park-profile-signout" onClick={() => void remove()}>
            Remove the key
          </button>
        </section>
      ) : null}
    </>
  );
}

/** `flow` is for tests: undefined means the deployment's own flow (null in the fixture world); a demo needs a real sign-in. */
export function ModelKeyControl({ flow, demo }: { flow?: ModelKeyFlow | null; demo: boolean }) {
  const live = useMemo(() => (flow === undefined ? liveModelKeyFlow() : flow), [flow]);
  if (!demo && !live) return null;
  return (
    <section aria-label="Organisation model key" className="park-profile-modelkey">
      <h2 className="park-profile-invoices-title">Organisation model key</h2>
      {demo || !live ? (
        <p className="park-profile-note">
          A demo session has no organisation key. Sign in with your own account to add one.
        </p>
      ) : (
        <Body flow={live} />
      )}
    </section>
  );
}
