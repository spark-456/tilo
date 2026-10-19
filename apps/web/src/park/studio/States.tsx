// UI-STUDIO-1: the shared empty, loading and error states (design/studio-v2 "Tilo R States"). Empty: a helper, a
// title, one line and one next step. Loading: still shapes of what is coming, never a spinner, a number or anything
// that implies work is running (HR-2). Error: what happened and what the person can do, with the action beside it.
import type { ReactNode } from "react";
import { parkKit } from "../shell/kit";
import "./studio.components.css";

/** Nothing to show yet: a helper picture, a title, one line and at most one next step. */
export function EmptyState({
  title,
  line,
  action,
  art,
}: {
  title: string;
  line: string;
  /** The one next step (a Button or a link); none when there is nothing to do. */
  action?: ReactNode;
  /** The helper picture; a happy helper by default. */
  art?: ReactNode;
}) {
  return (
    <div className="park-state park-state--empty">
      <div className="park-state__art" aria-hidden="true">
        {art ?? (parkKit().agent({ role: "connector", expr: "delighted" }, 88, false) as ReactNode)}
      </div>
      <h2 className="park-state__title">{title}</h2>
      <p className="park-state__line">{line}</p>
      {action ? <div className="park-state__actions">{action}</div> : null}
    </div>
  );
}

/** Still placeholder shapes in the reserved box (no motion: the shapes say "coming", not "working"). */
export function Skeleton({
  label,
  lines = 3,
  card = false,
}: {
  /** What is loading, for screen readers ("Loading worlds"). */
  label: string;
  lines?: number;
  /** A picture block above the lines, as a card that is coming. */
  card?: boolean;
}) {
  return (
    // biome-ignore lint/a11y/useSemanticElements: a loading status around still shapes, not a form output
    <div role="status" aria-label={label} className="park-skeleton">
      {card ? <span className="park-skeleton__block" aria-hidden="true" /> : null}
      {Array.from({ length: Math.max(1, lines) }, (_, i) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: still shapes with no identity
          key={i}
          aria-hidden="true"
          className={`park-skeleton__line park-skeleton__line--${(i % 3) + 1}`}
        />
      ))}
    </div>
  );
}

/** Something failed: says what happened and what to do, with the action (Try again, Connect, ...) right there. */
export function ErrorState({
  title,
  detail,
  action,
  secondary,
}: {
  title: string;
  /** What the person can do about it, in plain words. */
  detail: string;
  /** The one thing to do now. */
  action?: ReactNode;
  /** A quieter alternative ("Continue without it"). */
  secondary?: ReactNode;
}) {
  return (
    <div role="alert" className="park-state park-state--error">
      <div className="park-state__head">
        <span className="park-state__mark" aria-hidden="true">
          !
        </span>
        <h2 className="park-state__title">{title}</h2>
      </div>
      <p className="park-state__line">{detail}</p>
      {action || secondary ? (
        <div className="park-state__actions">
          {action}
          {secondary}
        </div>
      ) : null}
    </div>
  );
}
