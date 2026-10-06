// The boot splash (README "Interactions and motion": Boot; reference `Tilo App.dc.html` bootOn): a paper
// screen with the 56px logo, the 48px wordmark, a 200px bar and "Loading your city". It stays until the art
// engines have drawn the city, then goes at once. STATIC: the reference's sliding bar and 0.45s fade
// return with the motion restore (BQ-WEB-3), so the bar is drawn at rest.
export function BootSplash({ ready }: { ready: boolean }) {
  if (ready) return null;
  return (
    // biome-ignore lint/a11y/useSemanticElements: the design's own div; role and name are pinned by the spec
    <div role="status" aria-label="Loading Tilo" className="park-shell__boot">
      <div className="park-shell__bootlogo">
        <div className="park-shell__bootmark">
          <div className="park-shell__bootvisor">
            <div className="park-shell__bootdot" />
            <div className="park-shell__bootdot" />
          </div>
        </div>
        <div className="park-shell__bootword">tilo</div>
      </div>
      <div className="park-shell__bootstate">
        <div className="park-shell__boottrack">
          <div className="park-shell__bootfill" />
        </div>
        <div className="park-shell__boottext">Loading your city</div>
      </div>
    </div>
  );
}
