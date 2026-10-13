// ONBOARD-1: the first-run welcome: what Tilo does in three short steps. A modal dialog over the page; it holds the
// screen's one filled primary button (UX-1). Escape is handled by the layer.
import { useEffect, useId, useRef } from "react";
import { Button } from "../park/components";
import "./onboarding.css";
import { trapTab } from "./focus";
import { COPY } from "./steps";

export function Welcome({ onTour, onSkip }: { onTour: () => void; onSkip: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  const titleId = `onb-title-${id}`;
  const ledeId = `onb-lede-${id}`;
  useEffect(() => ref.current?.focus(), []);
  return (
    <div className="onb-scrim">
      <div
        ref={ref}
        // biome-ignore lint/a11y/useSemanticElements: the shell's dialogs are role="dialog" panels (Popover); one pattern for focus and Escape
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={ledeId}
        tabIndex={-1}
        className="onb-card"
        onKeyDown={trapTab}
      >
        <h2 id={titleId} className="onb-welcome-title">
          {COPY.welcomeTitle}
        </h2>
        <p id={ledeId} className="onb-body">
          {COPY.welcomeLede}
        </p>
        <ol className="onb-steps">
          {COPY.welcomeSteps.map((s, i) => (
            <li key={s.title} className="onb-step">
              <span className="onb-num" aria-hidden="true">
                {i + 1}
              </span>
              <span className="onb-step-text">
                <strong className="onb-step-title">{s.title}</strong>
                <span className="onb-body">{s.body}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="onb-note">{COPY.welcomeNote}</p>
        <div className="onb-row">
          <Button variant="primary" onClick={onTour}>
            {COPY.takeTour}
          </Button>
          <Button variant="secondary" onClick={onSkip}>
            {COPY.skipWelcome}
          </Button>
        </div>
      </div>
    </div>
  );
}
