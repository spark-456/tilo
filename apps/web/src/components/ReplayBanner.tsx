// NFR-22 (PRD 17.2): "model or quota failure offers labelled replays and a clear banner".
// Shared by the flow screens (FlowShell Loaded and Primary) and, when its composer goes live, Park
// Home (BQ-NFR22-3, BQ-NFR22-4). Fixed copy: the server's own text is never shown (BQ-NFR22-2).
// The one action is a link to the finished runs; no run is named and no sample data is made up
// (HR-4, BQ-NFR22-5). A persistent status region: no motion, no timers, no focus steal (HR-1).
import { useId } from "react";
import "./ReplayBanner.css";

export function ReplayBanner({ replaysHref = "/worlds" }: { replaysHref?: string }) {
  const id = useId();
  return (
    // biome-ignore lint/a11y/useSemanticElements: a persistent labelled status banner, not a form result (as App.tsx's fixture banner).
    <div className="replay-banner" data-testid="replay-banner" role="status" aria-labelledby={id}>
      <p id={id} className="replay-banner-title">
        Live models are unavailable
      </p>
      <p className="replay-banner-body">
        Nothing new was started. Finished runs can still be replayed.
      </p>
      <a className="replay-banner-link" href={replaysHref}>
        See finished runs and replays
      </a>
    </div>
  );
}
