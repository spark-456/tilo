// STUDIO-4: "Teach Tilo a skill" as three steps (design/studio-v2 "Tilo S Skills", views teach1..3): 1 Describe it,
// 2 Show an example, 3 Review the steps. Each step is a building going up (planned, under construction, complete), a
// still picture: nothing loops or moves by itself (HR-1..7). The flow is `useTeach`: live, step 1 posts
// /v1/skills/captures, step 2 posts .../{id}/version and Save posts /v1/skills, each once per click and shown only from
// the server's answer. "Try it once" has no route yet, so it stays disabled and says so: no run is ever pretended.
import { type RefObject, useEffect, useId, useRef, useState } from "react";
import type { User } from "../../api/types";
import { Button } from "../../components";
import { cx } from "../../components/cx";
import { ApiReadState } from "../../shared/ApiReadState";
import { icon, stepBuilding } from "./skillsKit";
import {
  CAP,
  CAPTURE_STEPS,
  DESCRIBE_SAMPLE,
  PLAN,
  QUESTION,
  SAVE,
  TRIGGERS,
  estimateSkillPlan,
  savedLine,
  sharedWith,
  stopsToAsk,
} from "./teachData";
import type { Teach } from "./useTeach";

export const WIZARD_STEPS = [
  { label: "Describe it", kind: "library", district: "research" },
  { label: "Show an example", kind: "workshop", district: "analysis" },
  { label: "Review the steps", kind: "desk", district: "delivery" },
] as const;

/** Why "Try it once" is off: a practice run has no route yet (STUDIO-4; never a pretend run). */
export const TRY_OFF =
  "Try it once is not available yet. Nothing runs until you save and use the skill.";
/** Why the example box is off: captures read a description only for now. */
export const EXAMPLE_OFF =
  "Adding an example file or recording your screen is not available yet. Tilo learns from your description for now.";

export interface WizardProps {
  t: Teach;
  user: User;
  night: boolean;
  /** Back to the gallery (Cancel, ← Back to skills). */
  onClose: () => void;
  /** After a save: open the new skill in the gallery. */
  onView: (id: string) => void;
  /** Read the page's data again (Retry after a failed write never sends the write again). */
  retryRead: () => void;
}

export function TeachWizard({ t, user, night, onClose, onView, retryRead }: WizardProps) {
  const [example, setExample] = useState(false);
  const ready = t.live ? t.steps.length > 0 : t.cap >= CAPTURE_STEPS;
  const step: 1 | 2 | 3 = t.saved || t.stage >= 1 ? 3 : example && ready ? 2 : 1;
  const heading = useRef<HTMLHeadingElement>(null);
  const shown = useRef(step);
  // A new step takes the reader to its heading (the step changed under the button they pressed).
  useEffect(() => {
    if (shown.current !== step) heading.current?.focus();
    shown.current = step;
  }, [step]);

  return (
    <div className="park-teach" data-testid="skills-teach">
      <div className="park-teach__top">
        <button type="button" className="park-teach__back" onClick={onClose}>
          ← Back to skills
        </button>
        <span className="park-teach__count">{`Step ${step} of 3`}</span>
      </div>
      <h1 className="park-skills-h1 park-teach__h1" tabIndex={-1}>
        Teach Tilo a skill
      </h1>
      <ol aria-label="Steps" className="park-teach__steps">
        {WIZARD_STEPS.map((s, i) => {
          const n = i + 1;
          const state = n < step || t.saved ? "complete" : n === step ? "construction" : "planned";
          return (
            <li
              key={s.label}
              className={cx("park-teach__step", n === step && "park-teach__step--now")}
              aria-current={n === step ? "step" : undefined}
            >
              <span className="park-teach__art" aria-hidden="true">
                {stepBuilding(s.kind, state, s.district, night)}
              </span>
              <span className="park-teach__pill">
                <span className="park-teach__n">{state === "complete" ? "✓" : n}</span>
                {s.label}
                <span className="park-sr-only">
                  {state === "complete" ? " (done)" : state === "planned" ? " (not yet)" : " (now)"}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      {step === 1 ? (
        <Describe t={t} heading={heading} onCancel={onClose} onNext={() => setExample(true)} />
      ) : step === 2 ? (
        <Example t={t} heading={heading} onBack={() => setExample(false)} />
      ) : t.saved ? (
        <Saved
          t={t}
          user={user}
          heading={heading}
          onView={() => (t.taught ? onView(t.taught.id) : onClose())}
          onAnother={() => {
            t.reset();
            setExample(false);
          }}
        />
      ) : (
        <Review t={t} user={user} heading={heading} />
      )}
      {t.live ? (
        <div data-skills-action-state="" style={{ blockSize: 176 }}>
          <div data-testid={t.failure != null ? "skills-teach-error" : undefined}>
            <ApiReadState
              error={t.failure}
              pending={false}
              retryRead={retryRead}
              title="The skill could not be updated"
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

type Heading = { heading: RefObject<HTMLHeadingElement> };

function Describe({
  t,
  heading,
  onCancel,
  onNext,
}: { t: Teach; onCancel: () => void; onNext: () => void } & Heading) {
  const nameId = useId();
  const descId = useId();
  // The name can wait until Save (step 3 asks for it); the description cannot.
  const missing = t.desc.trim() ? "" : "Write a sentence about the work first.";
  const triggers = t.live ? TRIGGERS.filter((o) => o.key === "ask") : TRIGGERS;
  return (
    <section className="park-teach__card" aria-labelledby={`${descId}-h`}>
      <div className="park-teach__intro">
        <h2 id={`${descId}-h`} ref={heading} tabIndex={-1} className="park-teach__h2">
          What should Tilo learn?
        </h2>
        <p className="park-teach__lede">
          Explain it the way you would to a new teammate. Plain words are perfect.
        </p>
      </div>
      <div className="park-teach__field">
        <label htmlFor={nameId} className="park-teach__label">
          {SAVE.nameLabel}
        </label>
        <input
          id={nameId}
          className="park-teach__input"
          value={t.name}
          maxLength={80}
          onChange={(e) => t.setName(e.target.value)}
        />
      </div>
      <div className="park-teach__field">
        <label htmlFor={descId} className="park-teach__label">
          What it does, step by step
        </label>
        <textarea
          id={descId}
          className="park-teach__text"
          value={t.desc}
          maxLength={4000}
          onChange={(e) => t.setDesc(e.target.value)}
        />
        <span className="park-teach__hint">Tilo turns this into steps for you to check.</span>
      </div>
      <fieldset className="park-teach__field park-teach__fieldset">
        <legend className="park-teach__label">When should Tilo use it?</legend>
        <div className="park-teach__chips">
          {triggers.map((o) => (
            <button
              key={o.key}
              type="button"
              aria-pressed={t.trig === o.key}
              className={cx("park-teach__chip", t.trig === o.key && "park-teach__chip--on")}
              onClick={() => t.setTrig(o.key)}
            >
              {o.label}
            </button>
          ))}
        </div>
        {t.live ? (
          <span className="park-teach__hint">
            For now a skill you teach runs when you ask for it.
          </span>
        ) : null}
      </fieldset>
      {t.live && t.busy ? (
        <output className="park-teach__hint">Reading your description…</output>
      ) : null}
      <div className="park-teach__foot">
        <button type="button" className="park-teach__quiet" onClick={onCancel}>
          Cancel
        </button>
        <span className="park-teach__why">{missing}</span>
        <Button
          variant="primary"
          disabled={missing !== "" || t.busy}
          onClick={() => {
            onNext();
            t.capture();
          }}
        >
          Next: show an example →
        </Button>
      </div>
    </section>
  );
}

function Example({ t, heading, onBack }: { t: Teach; onBack: () => void } & Heading) {
  const read: readonly string[] = t.live ? t.steps : CAP.describe;
  return (
    <section className="park-teach__card" aria-label="Show an example">
      <div className="park-teach__intro">
        <h2 ref={heading} tabIndex={-1} className="park-teach__h2">
          Show Tilo a good example
        </h2>
        <p className="park-teach__lede">
          Here is what Tilo read from your description. Check it before Tilo writes its steps.
        </p>
      </div>
      <div className="park-teach__read">
        <span className="park-teach__eyebrow">WHAT TILO READ</span>
        {t.live ? null : (
          <span className="park-teach__hint" data-testid="skills-describe-sample">
            {DESCRIBE_SAMPLE}
          </span>
        )}
        <ol className="park-teach__list">
          {read.map((s, i) => (
            <li key={`${i}:${s}`} className="park-teach__row">
              <span className="park-teach__num">{i + 1}</span>
              <span>{s}</span>
            </li>
          ))}
        </ol>
      </div>
      <div className="park-teach__drop" aria-disabled="true">
        <span className="park-teach__dropic" aria-hidden="true">
          +
        </span>
        <span className="park-teach__droptext">
          <strong>Drop a past example here, or record your screen once</strong>
          <span>{EXAMPLE_OFF}</span>
        </span>
        <Button variant="secondary" size="sm" disabled title={EXAMPLE_OFF}>
          Start recording
        </Button>
      </div>
      {t.live && t.busy ? (
        <output className="park-teach__hint">Writing Tilo’s steps…</output>
      ) : null}
      <div className="park-teach__foot">
        <button type="button" className="park-teach__quiet" onClick={onBack}>
          Back
        </button>
        <span className="park-teach__why" />
        <Button variant="primary" disabled={t.busy} onClick={t.next}>
          Next: review the steps →
        </Button>
      </div>
    </section>
  );
}

function Review({ t, user, heading }: { t: Teach; user: User } & Heading) {
  const v = t.version;
  const rows = v
    ? v.steps.map((s) => ({ text: s.text, tool: `${s.tool} · ${s.action}`, locked: s.locked }))
    : PLAN.map((p) => ({ text: p.text, tool: p.tool, locked: false }));
  const question = t.live
    ? v?.question
      ? { text: v.question.text, answers: [] as readonly string[] }
      : null
    : QUESTION;
  const est = estimateSkillPlan(PLAN, t.ask, t.currency);
  const sv = v?.estimates;
  const estimates = t.live
    ? [
        { k: "Each run (estimate)", v: sv ? `${sv.credits} credits` : "—" },
        { k: "Time (estimate)", v: sv ? `${sv.seconds} s` : "—" },
        { k: "Stops to ask", v: stopsToAsk(t.ask) },
      ]
    : [
        { k: "Each run", v: est.run },
        { k: "Time", v: est.time },
        { k: "Stops to ask", v: est.stops },
      ];
  const scopes = [
    { key: "me", label: "Just me" },
    ...(t.live ? [] : [{ key: "team", label: user.org } as const]),
  ] as const;
  const nameId = useId();
  return (
    <section className="park-teach__card" aria-label="Review the steps">
      <div className="park-teach__intro">
        <h2 ref={heading} tabIndex={-1} className="park-teach__h2">
          Here’s how Tilo will do it
        </h2>
        <p className="park-teach__lede">
          Switch on “Ask me first” wherever Tilo should stop and check with you.
        </p>
      </div>
      <div className="park-teach__name">
        <span className="park-teach__nameic" aria-hidden="true">
          {icon("people", 22)}
        </span>
        <span className="park-teach__field park-teach__grow">
          <label htmlFor={nameId} className="park-teach__label">
            {SAVE.nameLabel}
          </label>
          <input
            id={nameId}
            className="park-teach__input park-teach__input--plain"
            value={t.name}
            maxLength={80}
            onChange={(e) => t.setName(e.target.value)}
          />
        </span>
      </div>
      <ol className="park-teach__list">
        {rows.map((p, i) => {
          const on = t.ask[i] === true || p.locked;
          return (
            <li key={`${i}:${p.text}`} className="park-teach__row park-teach__row--step">
              <span className="park-teach__num">{i + 1}</span>
              <span className="park-teach__steptext">
                <span>{p.text}</span>
                <span className="park-teach__tool">{p.tool}</span>
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={on}
                disabled={p.locked}
                title={p.locked ? "Tilo always asks before this step." : undefined}
                className={cx("park-teach__ask", on && "park-teach__ask--on")}
                onClick={() => t.toggleAsk(i)}
              >
                Ask me first
                <span className="park-teach__track" aria-hidden="true">
                  <span className="park-teach__knob" />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {question ? (
        <div className="park-teach__question">
          <span className="park-teach__eyebrow">{QUESTION.eyebrow}</span>
          <p className="park-teach__q">{question.text}</p>
          {question.answers.length ? (
            <div className="park-teach__chips">
              {question.answers.map((a) => (
                <button
                  key={a}
                  type="button"
                  aria-pressed={t.qAns === a}
                  className={cx("park-teach__chip", t.qAns === a && "park-teach__chip--on")}
                  onClick={() => t.setQAns(a)}
                >
                  {a}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <dl className="park-teach__est">
        {estimates.map((m) => (
          <div key={m.k} className="park-teach__estrow">
            <dt>{m.k}</dt>
            <dd>{m.v}</dd>
          </div>
        ))}
      </dl>
      <fieldset className="park-teach__field park-teach__fieldset">
        <legend className="park-teach__label">{SAVE.who}</legend>
        <div className="park-teach__chips">
          {scopes.map((o) => (
            <button
              key={o.key}
              type="button"
              aria-pressed={t.scope === o.key}
              className={cx("park-teach__chip", t.scope === o.key && "park-teach__chip--on")}
              onClick={() => t.setScope(o.key)}
            >
              {o.label}
            </button>
          ))}
        </div>
      </fieldset>
      <p className="park-teach__hint">It starts as Learning. {SAVE.note}</p>
      <div className="park-teach__foot">
        <button type="button" className="park-teach__quiet" onClick={t.back}>
          Back
        </button>
        <span className="park-teach__why">
          {t.name.trim() ? "" : "Give the skill a name first."}
        </span>
        <Button variant="secondary" disabled aria-describedby={`${nameId}-try`}>
          Try it once
        </Button>
        <Button variant="primary" disabled={t.busy || !t.name.trim()} onClick={t.save}>
          Save skill
        </Button>
        <span id={`${nameId}-try`} className="park-teach__hint park-teach__full">
          {TRY_OFF}
        </span>
      </div>
    </section>
  );
}

function Saved({
  t,
  user,
  heading,
  onView,
  onAnother,
}: { t: Teach; user: User; onView: () => void; onAnother: () => void } & Heading) {
  return (
    <section className="park-teach__card park-teach__card--saved" aria-label="Saved">
      <h2 ref={heading} tabIndex={-1} className="park-teach__h2">
        “{t.taught?.name ?? t.name}” is now a skill
      </h2>
      <p className="park-teach__lede">{savedLine(sharedWith(t.scope, user.org), t.trig)}</p>
      <div className="park-teach__foot">
        <button type="button" className="park-teach__quiet" onClick={onAnother}>
          Teach another
        </button>
        <span className="park-teach__why" />
        <Button variant="primary" onClick={onView}>
          View in skills
        </Button>
      </div>
    </section>
  );
}
