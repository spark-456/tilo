// THROWAWAY (WEB-3b validation only).
import { type ReactNode, useEffect, useMemo } from "react";
import { useApp, useParkStore } from "../app/context";
import { getKit } from "./kit";
import { scenePins } from "./pins";
import { createSceneCache } from "./sceneCache";

export function CityBackdrop() {
  const app = useApp();
  const store = useParkStore();
  const get = useMemo(() => createSceneCache(getKit().TP.scene), []);
  const scene = get(app.time, app.motion);
  const pins = useMemo(() => scenePins(scene.spots, app.vw, app.vh), [scene, app.vw, app.vh]);
  useEffect(() => {
    store.setPins(pins);
  }, [store, pins]);
  const scale = Math.max(app.vw / 1600, app.vh / 1000);
  return (
    <div className="park-backdrop" data-testid="park-backdrop" aria-hidden="true">
      <div className="park-backdrop__scene" style={{ transform: `scale(${scale.toFixed(4)})` }}>
        {scene.el as ReactNode}
      </div>
      {app.page === "home" ? null : <div className="park-backdrop__veil" />}
    </div>
  );
}
