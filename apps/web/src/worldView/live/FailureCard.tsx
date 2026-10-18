// TILO-W: Failure card on top of Story (design/tilo-w PROMPT.md, Tilo W Parts.dc.html lines 52-64).
// Plain words: what happened, what was done, what was not, and what was safe: "Nothing was sent or paid."
import type React from "react";
import { Icon } from "../../design/tilo-t";
import type { RunView } from "../../park/pages/World/runView";
import type { RunEvent } from "../../park/pages/World/useRunEvents";

export interface FailureCardProps {
  readonly events?: readonly RunEvent[];
  readonly view?: RunView | null;
  readonly onRetry?: () => void;
  readonly step?: string;
  readonly what?: string;
  readonly safe?: string;
  readonly done?: readonly string[];
  readonly notDone?: readonly string[];
  readonly creditsNote?: string;
}

export function FailureCard({
  events = [],
  view,
  onRetry,
  step: propStep,
  what: propWhat,
  safe: propSafe,
  done: propDone,
  notDone: propNotDone,
  creditsNote: propCredits,
}: FailureCardProps) {
  const failedEvent = [...events].reverse().find((e) => e.type === "world.failed");
  const failedData = (failedEvent?.data ?? {}) as {
    step?: unknown;
    reason?: unknown;
    credits_used?: unknown;
    credits_cap?: unknown;
  };

  const stepName =
    propStep ??
    (typeof failedData.step === "string" ? failedData.step : null) ??
    view?.failure?.unit ??
    "Flights";

  const whatText =
    propWhat ??
    view?.failure?.reason ??
    (typeof failedData.reason === "string" ? failedData.reason : null) ??
    failedEvent?.summary ??
    "The airline site blocked automated search after 3 tries.";

  const timeText = failedEvent
    ? new Date(failedEvent.ts)
        .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
        .toLowerCase()
    : "4:02 pm";

  const safeText = propSafe ?? "Nothing was sent or paid.";

  // Derive completed / remaining items
  const doneItems =
    propDone ??
    (() => {
      const d: string[] = ["Plan"];
      for (const e of events) {
        if (e.type === "building.completed" && e.summary) {
          const m = e.summary.match(/completed\s+(.+)$/i);
          const name = m?.[1];
          d.push(name ? name : e.summary);
        }
      }
      if (d.length <= 1) return ["Plan", "Venue shortlist (kept)"];
      return Array.from(new Set(d));
    })();

  const notDoneItems = propNotDone ?? [
    "Flights",
    "Budget sheet",
    "Plan & invite",
    "Slides & site",
    "Review",
  ];

  const creditsUsed = typeof failedData.credits_used === "number" ? failedData.credits_used : 28;
  const creditsCap = typeof failedData.credits_cap === "number" ? failedData.credits_cap : 120;
  const creditsNote =
    propCredits ?? `${creditsUsed} of ${creditsCap} credits used. The venue shortlist is kept.`;

  return (
    <div role="alert" className="tw-fail-card" data-testid="world-failure-card">
      <div className="tw-fail-head">
        <span className="tw-fail-icon" aria-hidden="true">
          <Icon name="alert" size={18} />
        </span>
        <span className="tw-fail-title-group">
          <span className="tw-fail-title">Stopped at {stepName}</span>
          <span className="tw-fail-time">world.failed · {timeText}</span>
        </span>
      </div>

      <span className="tw-fail-what">{whatText}</span>

      <div className="tw-fail-safe">
        <Icon name="shield" size={18} />
        <span>{safeText}</span>
      </div>

      <div className="tw-fail-grid">
        <div className="tw-fail-col">
          <span className="tw-fail-col-label">DONE</span>
          {doneItems.map((item) => (
            <span key={item} className="tw-fail-item">
              <span className="tw-fail-item-check" aria-hidden="true">
                <Icon name="check" size={14} />
              </span>
              <span>{item}</span>
            </span>
          ))}
        </div>
        <div className="tw-fail-col">
          <span className="tw-fail-col-label">NOT DONE</span>
          {notDoneItems.map((item) => (
            <span key={item} className="tw-fail-item tw-fail-item--undone">
              <span className="tw-fail-item-minus" aria-hidden="true">
                <Icon name="minus" size={14} />
              </span>
              <span>{item}</span>
            </span>
          ))}
        </div>
      </div>

      <span className="tw-fail-cr">{creditsNote}</span>

      <div className="tw-fail-actions">
        {onRetry ? (
          <button type="button" className="tw-fail-btn tw-fail-btn--pri" onClick={onRetry}>
            <Icon name="refresh" size={16} />
            Try again
          </button>
        ) : (
          <button type="button" className="tw-fail-btn tw-fail-btn--pri" onClick={onRetry}>
            <Icon name="refresh" size={16} />
            Try again
          </button>
        )}
        <button type="button" className="tw-fail-btn tw-fail-btn--sec">
          Use a different flight site
        </button>
      </div>
    </div>
  );
}
