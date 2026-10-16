// SIMPLE-RUN-1: the one confirm card of the one-step start. It is the composer's plan card with the server's own
// words in it: the goal, what Tilo assumed in place of asking (each line can be changed), the price and one Start
// button. The person's click is the budget approval. Presentation only: the calls are HomePage's.
import type { PlanMakeChoice } from "@tilo/contracts";
import { useEffect, useState } from "react";
import type { Cadence, RunPlan } from "../../api/oneStep";
import { AppLink } from "../../shared/AppLink";
import { BudgetBar } from "./BudgetBar";
import { useRepeatWeekly } from "./RepeatWeekly";

export interface RunCardProps {
  readonly plan: RunPlan;
  /** A call is out (Start, or a changed line being priced again): every control waits. */
  readonly busy: boolean;
  /** True only after the person pressed Start; repricing a changed line must stay still. */
  readonly starting?: boolean;
  /** The plain reason the last step stopped, with Start as the retry. */
  readonly error: string | null;
  /** Start, with the weekly cadence when the person switched "Repeat weekly" on (FR-AGT-14). */
  readonly onStart: (repeat: Cadence | null, makeChoices: readonly PlanMakeChoice[]) => void;
  readonly onCancel: () => void;
  readonly onEdit: (field: string, answer: string) => void;
}

const credits = (n: number): string => `${Number.isInteger(n) ? n : n.toFixed(1)}`;

export function RunCard({
  plan,
  busy,
  starting = false,
  error,
  onStart,
  onCancel,
  onEdit,
}: RunCardProps) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [makeChoices, setMakeChoices] = useState<readonly PlanMakeChoice[]>(plan.makeChoices);
  useEffect(() => setMakeChoices(plan.makeChoices), [plan.makeChoices]);
  const repeat = useRepeatWeekly(busy);
  const price =
    plan.credits.min === plan.credits.max
      ? `${credits(plan.credits.max)} credits`
      : `${credits(plan.credits.min)}–${credits(plan.credits.max)} credits`;
  const usd = plan.usd === null ? "" : ` (about US$${plan.usd.toFixed(2)} at most)`;
  return (
    <>
      <div
        className={starting ? "park-home-plan park-home-plan--starting" : "park-home-plan"}
        data-testid="run-card"
      >
        {starting ? (
          <span className="park-home-run-blueprint" data-testid="run-blueprint" aria-hidden="true">
            BLUEPRINT · {plan.goal}
          </span>
        ) : null}
        <div className="park-home-plan__main">
          <div className="park-home-plan__head">
            <span className="park-home-tier">READY</span>
            <span className="park-home-plan__query">{plan.goal}</span>
          </div>
          <div className="park-home-meta">
            <span>
              <span className="park-home-meta__k">Cost</span>{" "}
              <span className="park-home-meta__v">{`${price}${usd}`}</span>
            </span>
            <span>
              <span className="park-home-meta__k">Time</span>{" "}
              <span className="park-home-meta__v">{plan.time}</span>
            </span>
          </div>
          <BudgetBar min={plan.credits.min} max={plan.credits.max} cap={plan.cap} />
          <p className="park-home-plan__sample" data-testid="budget-line">
            {`Start approves up to ${plan.cap} credits${plan.usd === null ? "" : ` (about US$${plan.usd.toFixed(2)})`}. You can pause it any time.`}
          </p>
          {plan.lines.length > 0 ? (
            <ol className="park-home-steps" aria-label="What Tilo assumed">
              {plan.lines.map((line, i) => (
                <li key={`${line.field ?? "line"}:${line.text}`} className="park-home-step">
                  {editing === i && line.field !== null ? (
                    <form
                      className="park-home-run__edit"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const answer = draft.trim();
                        if (answer === "" || line.field === null) return;
                        setEditing(null);
                        onEdit(line.field, answer);
                      }}
                    >
                      <input
                        aria-label={`Change: ${line.text}`}
                        value={draft}
                        maxLength={300}
                        // biome-ignore lint/a11y/noAutofocus: the person just asked to change this line
                        autoFocus
                        onChange={(e) => setDraft(e.target.value)}
                      />
                      <button type="submit" className="park-home-change" disabled={busy}>
                        Save
                      </button>
                    </form>
                  ) : (
                    <>
                      <span>{`Assumed: ${line.text}`}</span>
                      {line.field !== null ? (
                        <button
                          type="button"
                          className="park-home-run__link"
                          disabled={busy}
                          onClick={() => {
                            setEditing(i);
                            setDraft(line.text);
                          }}
                        >
                          Change
                        </button>
                      ) : null}
                    </>
                  )}
                </li>
              ))}
            </ol>
          ) : null}
          {makeChoices.length ? (
            <section className="park-home-makers" aria-label="Where to make it">
              {makeChoices.map((choice) => (
                <fieldset key={choice.deliverable} className="park-home-maker">
                  <legend>{`Deliverable ${choice.deliverable + 1}`}</legend>
                  {choice.options.map((option) => (
                    <div key={option.make_with} className="park-home-maker__option">
                      <label>
                        <input
                          type="radio"
                          name={`maker-${choice.deliverable}`}
                          value={option.make_with}
                          checked={choice.selected === option.make_with}
                          disabled={busy || option.status !== "ready"}
                          onChange={() =>
                            setMakeChoices((current) =>
                              current.map((item) =>
                                item.deliverable === choice.deliverable
                                  ? { ...item, selected: option.make_with }
                                  : item,
                              ),
                            )
                          }
                        />
                        <span>
                          {option.label}
                          {option.suggested ? " · Suggested" : ""}
                        </span>
                      </label>
                      {option.note ? <small>{option.note}</small> : null}
                      {option.status === "needs_setup" ? (
                        <AppLink to="/connectors">Connections</AppLink>
                      ) : null}
                    </div>
                  ))}
                </fieldset>
              ))}
            </section>
          ) : null}
          {repeat.control}
          {busy ? (
            // biome-ignore lint/a11y/useSemanticElements: a status line, not a form result
            <p role="status" className="park-home-plan__sample">
              Working on it…
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="park-home-plan__sample" data-testid="run-error">
              {error}
            </p>
          ) : null}
        </div>
        <div className="park-home-plan__actions">
          <button
            type="button"
            className="park-home-confirm"
            disabled={busy || repeat.invalid}
            aria-busy={busy ? true : undefined}
            onClick={() => onStart(repeat.cadence, makeChoices)}
          >
            {error ? "Try again" : "Start"}
          </button>
          <button type="button" className="park-home-change" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
      {starting ? <output className="park-home-start-status">Starting your world…</output> : null}
    </>
  );
}
