import { useState } from "react";
import { SampleBadge } from "./SampleBadge";

function wasDismissed(key: string): boolean {
  try {
    return localStorage.getItem(key) === "hidden";
  } catch {
    return false;
  }
}

/** FIRST-RUN: local display preference only; never persisted through the API. */
export function FirstRunBanner({
  first,
  page,
  person,
}: {
  first: boolean;
  page: string | null;
  person: string | null;
}) {
  const key = `tilo:first-run-banner:${JSON.stringify([person, page])}`;
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(() => new Set());
  if (!first || page === null || dismissed.has(key) || (person !== null && wasDismissed(key)))
    return null;
  const dismiss = () => {
    setDismissed((before) => new Set([...before, key]));
    if (person !== null) {
      try {
        localStorage.setItem(key, "hidden");
      } catch {
        /* device storage unavailable */
      }
    }
  };
  return (
    <aside className="park-first-run-banner" aria-label="Sample data">
      <span>
        <SampleBadge /> You are looking at sample data. It goes away after your first run.
      </span>
      <button type="button" onClick={dismiss} aria-label="Dismiss sample banner">
        Dismiss
      </button>
    </aside>
  );
}
