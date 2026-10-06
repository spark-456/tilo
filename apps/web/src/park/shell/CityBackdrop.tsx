// The city behind every page (README "City backdrop"): fixed, full-bleed, never clickable, hidden from
// assistive technology. The scene is a 1600x1000 picture scaled by max(vw/1600, vh/1000) and centred;
// `--veil` dims it on every page but Home. It is drawn once per `time|motion` (scene.ts) and STATIC here.
// Its three pin points go to `app.pins` through the provider (useReportPins).
import { useEffect } from "react";
import { useReportPins } from "../app/context";
import { sceneScale } from "../app/pins";
import type { BackdropScene } from "./scene";

export function CityBackdrop({
  scene,
  vw,
  vh,
  veiled,
}: { scene: BackdropScene | null; vw: number; vh: number; veiled: boolean }) {
  const report = useReportPins();
  useEffect(() => {
    if (scene) report(scene.pins);
  }, [scene, report]);
  const scale = sceneScale(vw, vh);
  return (
    <div aria-hidden="true" className="park-shell__backdrop">
      <div className="park-shell__scene" style={{ transform: `scale(${scale.toFixed(4)})` }}>
        {scene?.el}
      </div>
      <div className="park-shell__veil" style={{ opacity: veiled ? 1 : 0 }} />
    </div>
  );
}
