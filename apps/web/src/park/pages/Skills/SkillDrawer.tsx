// STUDIO-4: one skill's detail as a side sheet (a bottom sheet on a phone), design/studio-v2 "Tilo S Skills" view
// drawer: what it does, the steps it follows, its numbers (a dash where the Api serves none), tool access, the worlds
// it was used in, and its actions. Pause and Resume post `POST /v1/skills/{id}/state` on a live page and show the
// server's answer; "Test run" has no route yet and says so. Escape, the close button or the scrim close it.
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import type { Skill } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { type CurrencyCode, runMoney } from "../../app/ledgerKpis";
import { handDraft } from "../../chat/handoff";
import { Button } from "../../components";
import { cx } from "../../components/cx";
import { BookOpen, Globe2, Mail, PenLine } from "../../shared/icons";
import { agent, icon } from "./skillsKit";

export type StepType = "browse" | "read" | "write" | "email";

export function stepTypeOf(
  stepText: string,
  detail?: { tool?: string; action?: string; verb?: string },
): StepType {
  const tool = (detail?.tool ?? "").toLowerCase();
  const action = (detail?.action ?? "").toLowerCase();
  const verb = (detail?.verb ?? "").toLowerCase();
  const text = stepText.toLowerCase();

  if (
    tool.includes("mail") ||
    tool.includes("email") ||
    tool.includes("gmail") ||
    action.includes("mail") ||
    action.includes("email") ||
    action.includes("send_email") ||
    verb.includes("email") ||
    verb.includes("mail") ||
    /\b(?:email|emails|gmail|inbox|send email|draft email|mail)\b/i.test(text)
  ) {
    return "email";
  }

  if (
    tool.includes("browser") ||
    action.includes("browse") ||
    action.includes("navigate") ||
    action.includes("scrape") ||
    verb.includes("browse") ||
    /\b(?:browse|website|webpage|browser|url|http|navigate|open tab|search web)\b/i.test(text)
  ) {
    return "browse";
  }

  if (
    tool.includes("writer") ||
    action.includes("write") ||
    action.includes("compose") ||
    action.includes("draft") ||
    action.includes("generate") ||
    verb.includes("write") ||
    /\b(?:write|compose|draft|create|generate|summary|summarise|outline|reply|plan|report)\b/i.test(
      text,
    )
  ) {
    return "write";
  }

  return "read";
}

function StepTypeIcon({ type }: { type: StepType }) {
  switch (type) {
    case "browse":
      return <Globe2 size={16} aria-hidden="true" />;
    case "read":
      return <BookOpen size={16} aria-hidden="true" />;
    case "write":
      return <PenLine size={16} aria-hidden="true" />;
    case "email":
      return <Mail size={16} aria-hidden="true" />;
  }
}

export type Shown = Skill["st"] | "paused";

export const STATUS: Record<Shown, { label: string; tone: string }> = {
  trusted: { label: "Trusted", tone: "ok" },
  learning: { label: "Learning", tone: "lilac" },
  review: { label: "Needs an answer", tone: "amber" },
  paused: { label: "Paused", tone: "chip" },
  draft: { label: "Draft", tone: "chip" },
};

export const statusOf = (s: Skill, paused: boolean): { label: string; tone: string } =>
  s.builtin ? { label: "Built-in", tone: "chip" } : STATUS[paused || s.paused ? "paused" : s.st];

/** A practice or test run has no route yet (STUDIO-4): the button says so, never pretends. */
export const RUN_OFF = "Test runs are not available yet. Nothing was started.";

const LEVELS = ["Off", "Read", "Draft", "Act"] as const;
const money = (v: number | undefined, currency: CurrencyCode): string =>
  v == null ? "—" : runMoney(v, currency);

export interface DrawerProps {
  app: AppCtx;
  skill: Skill;
  paused: boolean;
  currency: CurrencyCode;
  /** Pause or resume: a promise that settles once the change is recorded (or refused). Null when it cannot be done here. */
  onPause: ((skill: Skill, pause: boolean) => Promise<void> | undefined) | null;
  /** Why pausing cannot be done from here, shown beside the disabled button. */
  pauseOff: string;
  onTeach: () => void;
  onClose: () => void;
  onRun?:
    | ((skill: Skill, values: Record<string, string>, files: File[]) => Promise<void> | void)
    | undefined;
  onEdit?: ((skill: Skill, name: string, steps: string[]) => Promise<void>) | undefined;
  onDelete?: ((skill: Skill) => Promise<void>) | undefined;
  /** The step-fix form (a live owned skill), placed under the steps. */
  fix?: ReactNode;
}

export function SkillDrawer({
  app,
  skill,
  paused,
  currency,
  onPause,
  pauseOff,
  onTeach,
  onClose,
  onRun,
  onEdit,
  onDelete,
  fix,
}: DrawerProps) {
  const title = useId();
  const close = useRef<HTMLButtonElement>(null);
  const [acc, setAcc] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<Record<string, File>>({});
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState("");
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(skill.name);
  const [editSteps, setEditSteps] = useState([...skill.steps]);
  const [deleting, setDeleting] = useState(false);
  const [mutationBusy, setMutationBusy] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const st = statusOf(skill, paused);
  const isPaused = paused || skill.paused === true;
  const inputs = skill.details?.inputs.length
    ? skill.details.inputs
    : (skill.catalog?.inputs ?? []);
  const runInputs = inputs.length
    ? inputs
    : [{ name: "task", label: "Task details", kind: "text", required: true }];
  const needsBrowser =
    skill.steps.some(
      (step) =>
        /\b(?:open|navigate|click|play|type|fill)\b/i.test(step) &&
        /\b(?:browser|website|webpage|youtube|https?:\/\/|\.com\b)/i.test(step),
    ) ||
    skill.details?.steps.some(
      (step) => /browser|browse_web/i.test(step.tool) || step.action === "browse_web",
    ) === true ||
    skill.catalog?.tools.some((tool) => /browser|browse_web/i.test(tool)) === true;
  const readyToRun = runInputs.every(
    (input) =>
      !input.required ||
      (input.kind === "file" ? Boolean(files[input.name]) : Boolean(values[input.name]?.trim())),
  );

  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const stats = [
    { k: "Runs", v: skill.runs == null ? "—" : String(skill.runs) },
    { k: "Success", v: skill.rate != null ? `${skill.rate}%` : "—" },
    { k: "Last run", v: skill.last || "—" },
    { k: "Cost a run", v: money(skill.now, currency) },
  ];
  const meta = [
    skill.builtin
      ? `Shipped with Tilo · version ${skill.from}`
      : skill.owner
        ? `Owned by ${skill.owner}`
        : "",
    skill.team,
    skill.used.length
      ? `used in ${skill.used.length} ${skill.used.length === 1 ? "world" : "worlds"}`
      : "",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: a click-away layer; Escape is the keyboard way out (above)
    <div
      className="park-skill-scrim"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* biome-ignore lint/a11y/useSemanticElements: a side sheet over its own scrim; Escape and focus are handled here */}
      <aside role="dialog" aria-modal="true" aria-labelledby={title} className="park-skill-drawer">
        <div className="park-skill-drawer__head">
          <span className="park-skill-drawer__art" aria-hidden="true">
            {agent({ role: skill.role, expr: isPaused ? "sleepy" : "focused" }, 56, app.night)}
          </span>
          <div className="park-skill-drawer__titles">
            <div className="park-skill-drawer__titlerow">
              <h2 id={title} className="park-skill-drawer__h2">
                {skill.name}
              </h2>
              <span className={`park-skill-chip park-skill-chip--${st.tone}`}>{st.label}</span>
            </div>
            {meta ? <div className="park-skill-drawer__meta">{meta}</div> : null}
          </div>
          <button
            ref={close}
            type="button"
            aria-label="Close"
            className="park-skill-drawer__close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className="park-skill-drawer__body">
          <section className="park-skill-drawer__sec" aria-label="How Tilo uses this skill">
            <h3 className="park-skill-drawer__h3">How Tilo uses this skill</h3>
            {skill.description ? (
              <p className="park-skill-drawer__p">
                <strong>When Tilo picks it:</strong> {skill.description}
              </p>
            ) : null}
            {skill.tools.length ? (
              <p className="park-skill-drawer__p">
                <strong>What it needs:</strong> {skill.tools.map(([tool]) => tool).join(", ")}
              </p>
            ) : null}
            {skill.catalog?.tools.length ? (
              <p className="park-skill-drawer__p">
                <strong>Connectors it uses:</strong> {skill.catalog.tools.join(", ")}
              </p>
            ) : null}
            <Button
              variant="secondary"
              onClick={() => {
                handDraft("", {
                  id: skill.id,
                  kind: skill.builtin ? "library" : "taught",
                  scope: skill.builtin ? "library" : skill.team ? "team" : "mine",
                  name: skill.name,
                  purpose: skill.description ?? "",
                  inputs: [],
                  tools: skill.tools.map(([tool]) => tool),
                  version: skill.from,
                });
                onClose();
                app.go("home");
              }}
            >
              Try it
            </Button>
            <p className="park-skill-drawer__p">
              Opens Home with this skill tagged. Describe your task before starting.
            </p>
          </section>
          {skill.steps.length ? (
            <section className="park-skill-drawer__sec">
              <h3 className="park-skill-drawer__h3">Steps it follows</h3>
              <ol className="park-skill-drawer__steps">
                {skill.steps.map((s, i) => {
                  const stepType = stepTypeOf(s, skill.details?.steps[i]);
                  return (
                    <li key={`${i + 1}-${s}`} className="park-skill-drawer__step">
                      <span className="park-skill-drawer__n">{i + 1}</span>
                      <span
                        className="park-skill-drawer__step-icon"
                        aria-hidden="true"
                        title={stepType}
                      >
                        <StepTypeIcon type={stepType} />
                      </span>
                      <span className="park-skill-drawer__step-content">
                        <span>{s}</span>
                        {skill.details?.steps[i] ? (
                          <span className="park-skill-chip">
                            {skill.details.steps[i].tool} · {skill.details.steps[i].action}
                          </span>
                        ) : null}
                        {skill.fix?.asks[i] ? (
                          <span className="park-skill-chip park-skill-chip--amber">
                            Asks you first
                          </span>
                        ) : null}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </section>
          ) : null}
          {inputs.length ? (
            <section className="park-skill-drawer__sec" aria-label="Inputs for this skill">
              <h3 className="park-skill-drawer__h3">What you provide</h3>
              <ul>
                {inputs.map((input) => (
                  <li key={input.name}>
                    {input.label}
                    {input.required ? " (required)" : " (optional)"}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <form
            className="park-skill-run"
            onSubmit={(event) => {
              event.preventDefault();
              if (!onRun || running || !readyToRun || needsBrowser || isPaused) return;
              setRunning(true);
              setRunError("");
              Promise.resolve(onRun(skill, values, Object.values(files)))
                .catch((error: unknown) => {
                  setRunError(
                    error instanceof Error ? error.message : "The skill could not start.",
                  );
                })
                .finally(() => setRunning(false));
            }}
          >
            <h3 className="park-skill-drawer__h3">Run this skill</h3>
            {runInputs.map((input) => (
              <label
                key={input.name}
                htmlFor={`skill-run-input-${input.name}`}
                className="park-teach__field"
              >
                <span className="park-teach__label">
                  {input.label}
                  {input.required ? (
                    <span className="park-teach__required"> (required)</span>
                  ) : (
                    " (optional)"
                  )}
                </span>
                {input.kind === "file" ? (
                  <input
                    id={`skill-run-input-${input.name}`}
                    aria-label={input.label}
                    type="file"
                    className="park-teach__input park-teach__fileinput"
                    required={input.required}
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      setFiles((before) => {
                        const next = { ...before };
                        if (file) next[input.name] = file;
                        else delete next[input.name];
                        return next;
                      });
                    }}
                  />
                ) : (
                  <input
                    id={`skill-run-input-${input.name}`}
                    aria-label={input.label}
                    className="park-teach__input"
                    type={
                      input.kind === "date"
                        ? "date"
                        : input.kind === "number"
                          ? "number"
                          : input.kind === "url"
                            ? "url"
                            : "text"
                    }
                    required={input.required}
                    value={values[input.name] ?? ""}
                    onChange={(event) =>
                      setValues((before) => ({ ...before, [input.name]: event.target.value }))
                    }
                  />
                )}
              </label>
            ))}
            {needsBrowser ? (
              <p className="park-teach__hint">Needs browser control (coming)</p>
            ) : null}
            <Button
              variant="primary"
              type="submit"
              disabled={!onRun || !readyToRun || needsBrowser || isPaused || running}
            >
              Run skill
            </Button>
            {runError ? <p role="alert">{runError}</p> : null}
          </form>
          {skill.details?.hosts.length ? (
            <p className="park-skill-drawer__p">Approved sites: {skill.details.hosts.join(", ")}</p>
          ) : null}
          {skill.details?.estimatedCredits != null ? (
            <p className="park-skill-drawer__p">
              Estimated cost: {skill.details.estimatedCredits} credits per run
            </p>
          ) : null}
          {fix}
          {onEdit ? (
            <section className="park-skill-drawer__sec" aria-label="Edit this skill">
              <Button variant="secondary" onClick={() => setEditing((shown) => !shown)}>
                Edit skill
              </Button>
              {editing ? (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!editName.trim() || editSteps.some((step) => !step.trim()) || mutationBusy)
                      return;
                    setMutationBusy(true);
                    setMutationError("");
                    onEdit(
                      skill,
                      editName.trim(),
                      editSteps.map((step) => step.trim()),
                    )
                      .then(() => setEditing(false))
                      .catch((error: unknown) =>
                        setMutationError(
                          error instanceof Error ? error.message : "The skill could not be saved.",
                        ),
                      )
                      .finally(() => setMutationBusy(false));
                  }}
                >
                  <label className="park-teach__field">
                    <span className="park-teach__label">Skill name</span>
                    <input
                      aria-label="Skill name"
                      className="park-teach__input"
                      required
                      value={editName}
                      onChange={(event) => setEditName(event.target.value)}
                    />
                  </label>
                  {editSteps.map((step, index) => (
                    // Steps cannot be reordered or removed while this form is open.
                    // biome-ignore lint/suspicious/noArrayIndexKey: The fixed saved-step order identifies each field.
                    <label key={index} className="park-teach__field">
                      <span className="park-teach__label">Step {index + 1}</span>
                      <input
                        aria-label={`Step ${index + 1}`}
                        className="park-teach__input"
                        required
                        value={step}
                        onChange={(event) =>
                          setEditSteps((before) =>
                            before.map((item, i) => (i === index ? event.target.value : item)),
                          )
                        }
                      />
                    </label>
                  ))}
                  <Button
                    variant="primary"
                    type="submit"
                    disabled={
                      mutationBusy || !editName.trim() || editSteps.some((step) => !step.trim())
                    }
                  >
                    Save changes
                  </Button>
                </form>
              ) : null}
            </section>
          ) : null}
          {onDelete ? (
            <section className="park-skill-drawer__sec" aria-label="Delete this skill">
              <Button variant="secondary" onClick={() => setDeleting(true)}>
                Delete skill
              </Button>
              {deleting ? (
                <div>
                  <p>Delete “{skill.name}” from My skills?</p>
                  <Button
                    variant="secondary"
                    disabled={mutationBusy}
                    onClick={() => setDeleting(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    disabled={mutationBusy}
                    onClick={() => {
                      setMutationBusy(true);
                      setMutationError("");
                      onDelete(skill)
                        .catch((error: unknown) =>
                          setMutationError(
                            error instanceof Error
                              ? error.message
                              : "The skill could not be deleted.",
                          ),
                        )
                        .finally(() => setMutationBusy(false));
                    }}
                  >
                    Confirm delete
                  </Button>
                </div>
              ) : null}
            </section>
          ) : null}
          {mutationError ? <p role="alert">{mutationError}</p> : null}
          {skill.builtin ? null : (
            <dl className="park-skill-drawer__stats">
              {stats.map((m) => (
                <div key={m.k} className="park-skill-drawer__stat">
                  <dt>{m.k}</dt>
                  <dd>{m.v}</dd>
                </div>
              ))}
            </dl>
          )}
          {skill.first != null && skill.now != null && skill.first > 0 ? (
            <p className="park-skill-drawer__cost">
              <strong>
                {skill.now < skill.first
                  ? `${Math.round((1 - skill.now / skill.first) * 100)}% cheaper than the first run`
                  : "Same as the first run"}
              </strong>
              <span>{`First run ${money(skill.first, currency)} · Now ${money(skill.now, currency)}`}</span>
            </p>
          ) : null}
          {skill.tools.length ? (
            <section className="park-skill-drawer__sec">
              <div className="park-skill-drawer__row">
                <h3 className="park-skill-drawer__h3">Tool access for this skill</h3>
                <button
                  type="button"
                  className="park-skill-link"
                  onClick={() => app.go("connectors")}
                >
                  Manage connectors
                </button>
              </div>
              {skill.tools.map(([tool, level]) => {
                const lv = acc[tool] ?? level;
                return (
                  <div key={tool} className="park-skill-drawer__tool">
                    <span className="park-skill-drawer__toolname">{tool}</span>
                    <fieldset aria-label={`${tool} access`} className="park-skill-seg">
                      {LEVELS.map((label, i) => (
                        <button
                          key={label}
                          type="button"
                          aria-pressed={lv === i}
                          className={cx(
                            "park-skill-seg__btn",
                            lv === i && "park-skill-seg__btn--on",
                          )}
                          onClick={() => {
                            setAcc((p) => ({ ...p, [tool]: i }));
                            app.toast(
                              `${tool} access set to ${label} on this page only. Team rules still apply`,
                            );
                          }}
                        >
                          {label}
                        </button>
                      ))}
                    </fieldset>
                  </div>
                );
              })}
            </section>
          ) : null}
          {skill.builtin ? null : (
            <section className="park-skill-drawer__sec">
              <h3 className="park-skill-drawer__h3">Used in</h3>
              {skill.used.length ? (
                <div className="park-skill-drawer__used">
                  {skill.used.map((w) => (
                    <button
                      key={w}
                      type="button"
                      className="park-skill-link"
                      onClick={() => app.go("world", { id: w })}
                    >
                      {w}
                      {icon("chevR", 12)}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="park-skill-drawer__p park-skills-drawer__empty">
                  Not used in any world yet.
                </p>
              )}
            </section>
          )}
        </div>
        <div className="park-skill-drawer__foot">
          <Button variant="primary" onClick={onTeach}>
            Teach a new version
          </Button>
          {skill.builtin ? null : (
            <>
              <Button variant="secondary" disabled title={RUN_OFF}>
                {skill.st === "draft" ? "Try run" : "Test run"}
              </Button>
              <Button
                variant="secondary"
                disabled={onPause === null || busy}
                title={onPause === null ? pauseOff : undefined}
                onClick={() => {
                  if (!onPause) return;
                  const sent = onPause(skill, !isPaused); // a sample-data pause is this page's only: no wait
                  if (sent) {
                    setBusy(true);
                    sent.finally(() => setBusy(false));
                  }
                }}
              >
                {isPaused ? "Resume" : "Pause"}
              </Button>
            </>
          )}
          <p className="park-skill-drawer__note">
            {skill.builtin
              ? "Built-in skills are picked by agents during a run."
              : `${RUN_OFF.replace(" Nothing was started.", "")}${onPause === null ? ` ${pauseOff}` : ""}`}
          </p>
        </div>
      </aside>
    </div>
  );
}
