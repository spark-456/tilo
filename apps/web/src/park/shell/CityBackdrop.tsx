// The city behind every page (README "City backdrop"): fixed, full-bleed, never clickable, hidden from
// assistive technology. The scene is a 1600x1000 picture scaled by max(vw/1600, vh/1000) and centred;
// `--veil` dims it on every page but Home. It is drawn once per `time|motion` (scene.ts); its cars and walkers
// run on their own and are paused (`data-paused`) under the veil, while the world loader is open and in a hidden tab, and half are not drawn
// (`data-lite`) in a narrow window or on a weak device. Its three pin points go to `app.pins` through the provider (useReportPins).
// The city is drawn after the page (cityStart.ts); until then a poster fills the same fixed layer, so the city arriving moves nothing.
import { useEffect } from "react";
import { useReportPins } from "../app/context";
import { sceneScale } from "../app/pins";
import type { BackdropScene } from "./scene";

export function CityBackdrop({
  scene,
  vw,
  vh,
  veiled,
  lite,
  hidden,
  loading = false,
}: {
  scene: BackdropScene | null;
  vw: number;
  vh: number;
  veiled: boolean;
  lite: boolean;
  hidden: boolean;
  /** The world loader is open: the city holds still while it runs (the reference does). */
  loading?: boolean;
}) {
  const report = useReportPins();
  useEffect(() => {
    if (scene) report(scene.pins);
  }, [scene, report]);
  const scale = sceneScale(vw, vh);
  return (
    <div
      aria-hidden="true"
      className="park-shell__backdrop"
      data-paused={veiled || hidden || loading ? "" : undefined}
      data-lite={lite ? "" : undefined}
    >
      {scene ? null : <div className="park-shell__poster" data-testid="park-shell-poster" />}
      <div className="park-shell__scene" style={{ transform: `scale(${scale.toFixed(4)})` }}>
        {scene?.el}
      </div>
      <div className="park-shell__veil" style={{ opacity: veiled ? 1 : 0 }} />
    </div>
  );
}
