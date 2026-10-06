// One card, every channel (PRD 10.3), as the web draws it after design/source "Tilo 2 Balanced
// Refined.dc.html" 2-1 and 2-2: the rung in words, building and agent by name, what happened, why
// it matters, 2 to 3 options with the suggested one marked and explained, an add-context field and
// Show me / Snooze / Delegate. A card names its own safe default and timeout (PRD 10.3). The
// options are choices; the one filled button sends the chosen one, so a gate's authorising tap is
// always the person's own. Show me, Snooze and Delegate are not built: aria-disabled placeholders.
import type { Card, Layout } from "@tilo/contracts";
import { type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import type { TiloClient } from "../api/client";
import { Placeholder } from "../screens/Placeholder";
import { findItem } from "../screens/findItem";
import { Chip, Soon } from "../screens/kit";
import { describeError } from "../screens/remote";
import { agentNames } from "../world/runSummary";
import { RUNG } from "./queue";

/** The state of one answer: the option sent and not yet confirmed by its closing event (HR-1). */
export interface Answer {
  readonly pending: string | null;
  readonly error: string | null;
  /** The client took the answer but no closing event was recorded in time: the controls are
   * usable again and nothing is claimed as done. */
  readonly unconfirmed: boolean;
  readonly send: (optionId: string, context: string) => void;
}

/** How long a sent answer waits for its closing event before the card says nothing came back. */
export const CONFIRM_MS = 20_000;

/** Sends an answer through the client. The card is not closed by this: only the recorded event
 * that answers it closes it. Until then `pending` holds; after `confirmMs` without that event the
 * answer is `unconfirmed` and can be sent again. The state belongs to one card: the screen keys
 * the component that calls this by the request, so a redraft's new request starts fresh. */
export function useAnswer(client: TiloClient, cardId: string, confirmMs = CONFIRM_MS): Answer {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const busy = useRef(false);
  const live = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      clearTimeout(timer.current);
    };
  }, []);
  const send = useCallback(
    (optionId: string, context: string) => {
      if (busy.current) return;
      busy.current = true;
      clearTimeout(timer.current);
      setPending(optionId);
      setError(null);
      setUnconfirmed(false);
      Promise.resolve()
        .then(() =>
          client.answerCard(
            cardId,
            context ? { option_id: optionId, context } : { option_id: optionId },
          ),
        )
        .then(() => {
          timer.current = setTimeout(() => {
            busy.current = false;
            if (!live.current) return;
            setPending(null);
            setUnconfirmed(true);
          }, confirmMs);
        })
        .catch((e: unknown) => {
          busy.current = false;
          if (!live.current) return;
          setPending(null);
          setError(describeError("send your answer", e));
        });
    },
    [client, cardId, confirmMs],
  );
  return { pending, error, unconfirmed, send };
}

const ACTIONS = { show_me: "Show me", snooze: "Snooze", delegate: "Delegate to Director" } as const;

/** 3600 -> "1 h", 900 -> "15 min", 45 -> "45 s". */
const duration = (s: number): string =>
  s < 60 ? `${s} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.round(s / 360) / 10} h`;

/** Rung, building and agent by name, what happened and why it matters. */
export function CardHead({ card, layout }: { card: Card; layout: Layout | null }) {
  const rung = RUNG[card.rung];
  const agent = layout ? agentNames(layout).get(card.header.agent) : undefined;
  const building = layout ? findItem(layout, card.header.building)?.name : undefined;
  return (
    <>
      <div className="need-head">
        <Chip tone={rung.tone}>{rung.label}</Chip>
        <span className="need-where">{`${building ?? "A building"} · ${agent ?? "An agent"}`}</span>
      </div>
      <h3 className="need-what">{card.what_happened}</h3>
      <p className="need-why">{card.why_it_matters}</p>
    </>
  );
}

/** The options, the add-context field, the safe-default line and the one filled button. Without an
 * `answer` the card is read-only: the options are shown and `footer` (or a placeholder) stands in. */
export function CardOptions({
  card,
  answer,
  footer,
  preselect = true,
}: { card: Card; answer: Answer | null; footer?: ReactNode; preselect?: boolean }) {
  const group = useId();
  // `preselect` false (a T3 or irreversible gate): nothing is chosen until the person chooses.
  const [choice, setChoice] = useState<string | undefined>(
    preselect ? (card.options.find((o) => o.suggested) ?? card.options[0])?.id : undefined,
  );
  const [context, setContext] = useState("");
  const chosen = card.options.find((o) => o.id === choice);
  const locked = !answer || answer.pending !== null;
  const safe = card.options.find((o) => o.id === card.safe_default)?.label ?? "the safe option";
  const gate = card.kind === "gate";
  return (
    <>
      <div role="radiogroup" aria-label="Your options" className="need-options">
        {card.options.map((o) => (
          <label
            key={o.id}
            className="need-option"
            data-selected={o.id === choice ? "true" : undefined}
          >
            <input
              type="radio"
              name={group}
              value={o.id}
              checked={o.id === choice}
              disabled={locked}
              onChange={() => setChoice(o.id)}
            />
            <span className="need-option-text">
              <span>
                <b>{o.label}</b>
                {o.suggested && <Chip tone="suggested">Suggested</Chip>}
              </span>
              {o.reason && <span className="bitem-sub">{o.reason}</span>}
              {o.irreversible && <span className="bitem-sub">Cannot be undone</span>}
            </span>
          </label>
        ))}
      </div>
      {card.add_context && (
        <label className="field need-context">
          Add context (optional)
          <textarea
            value={context}
            disabled={locked}
            rows={2}
            onChange={(e) => setContext(e.target.value)}
          />
        </label>
      )}
      <p className="section-note need-default">
        {gate
          ? `This gate never opens by itself. If nobody answers in ${duration(card.timeout)}, it stays closed (${safe}).`
          : `If nobody answers in ${duration(card.timeout)}, Tilo applies the safe default: ${safe}.`}
      </p>
      <div className="need-bar">
        <div className="need-actions">
          {answer ? (
            <button
              type="button"
              className="primary"
              disabled={answer.pending !== null || !chosen}
              aria-busy={answer.pending !== null ? "true" : undefined}
              onClick={() => chosen && answer.send(chosen.id, context)}
            >
              {chosen?.label ?? "Choose an option"}
            </button>
          ) : (
            (footer ?? (chosen && <Placeholder label={chosen.label} compact />))
          )}
          {card.actions.length > 0 && <Soon labels={card.actions.map((a) => ACTIONS[a])} />}
        </div>
        <div className="need-status" aria-live="polite">
          {answer?.pending && <span>Waiting for confirmation…</span>}
          {answer?.unconfirmed && (
            <span>
              No confirmation has been recorded for your answer yet. You can answer again.
            </span>
          )}
        </div>
      </div>
      {answer?.error && (
        <p className="need-error" role="alert">
          {answer.error}
        </p>
      )}
    </>
  );
}

/** The whole card; `children` sit between what it says and its options (a gate's exact action). */
export function CardView({
  card,
  layout,
  answer,
  footer,
  children,
}: {
  card: Card;
  layout: Layout | null;
  answer: Answer | null;
  footer?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <article className="need-card" data-testid="need-card" data-rung={card.rung}>
      <CardHead card={card} layout={layout} />
      {children}
      <CardOptions card={card} answer={answer} footer={footer} />
    </article>
  );
}
