// JUDGE-FIRST-RUN F6: what Home draws while its first reads are out, so a direct load is never a blank page. Still
// shapes only (no spinner, no progress, no number): nothing here claims work is happening.
export function HomeSkeleton() {
  return (
    // biome-ignore lint/a11y/useSemanticElements: a loading status around still shapes, not a form output
    <div role="status" aria-label="Loading Home" className="park-home-top">
      <div className="park-home-hero park-home-hero--loading">
        <span className="park-home-skeleton park-home-skeleton--short" aria-hidden="true" />
        <span className="park-home-skeleton park-home-skeleton--wide" aria-hidden="true" />
        <span className="park-home-skeleton park-home-skeleton--mid" aria-hidden="true" />
      </div>
    </div>
  );
}
