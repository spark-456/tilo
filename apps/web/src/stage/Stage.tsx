import { Application, Graphics } from "pixi.js";
import { useEffect, useRef, useState } from "react";
import tokens from "../design/tokens";
import { useMediaQuery } from "../hooks/useMediaQuery";
import {
  type CameraState,
  INITIAL_CAMERA,
  PAN_STEP_PX,
  ZOOM_STEP,
  cameraTransform,
  getCameraPanDurationMs,
  panCamera,
  zoomCamera,
} from "./camera";

// PRD 9.7 "No WebGL2: the Story lens and a static world image take over."
const hasWebgl2 = (): boolean => {
  try {
    return !!document.createElement("canvas").getContext("webgl2");
  } catch {
    return false;
  }
};

// PRD 9.1/9.7: a static isometric grid, tile size from the design tokens. The
// diamond lattice is two families of parallel lines (slopes +-th/tw) spaced
// th apart vertically, both passing through the top vertex of the diamond
// centred on the world origin. Drawn in world coordinates across exactly the
// visible world rect, so it covers the stage at every zoom and pan.
function drawIsoGrid(
  g: Graphics,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  color: number,
): void {
  g.clear();
  const { tileWidth: tw, tileHeight: th } = tokens.stage;
  const c0 = -th / 2;
  for (const slope of [th / tw, -th / tw]) {
    const cMin = Math.min(y0 - slope * x0, y0 - slope * x1);
    const cMax = Math.max(y1 - slope * x0, y1 - slope * x1);
    const kMax = Math.ceil((cMax - c0) / th);
    for (let k = Math.floor((cMin - c0) / th); k <= kMax; k++) {
      const c = c0 + k * th;
      g.moveTo(x0, slope * x0 + c).lineTo(x1, slope * x1 + c);
    }
  }
  g.stroke({ width: 1, color, alpha: 0.35, pixelLine: true });
}

/** Reads zoom (a) and translation (e, f) from a computed `matrix(...)`. */
function parseCameraMatrix(transform: string): { a: number; e: number; f: number } {
  const n = (/^matrix\(([^)]+)\)$/.exec(transform)?.[1] ?? "").split(",").map(Number);
  const [a = 1, , , , e = 0, f = 0] = n.length === 6 ? n : [];
  return { a, e, f };
}

const KEY_PAN: Record<string, [number, number]> = {
  ArrowLeft: [PAN_STEP_PX, 0],
  ArrowRight: [-PAN_STEP_PX, 0],
  ArrowUp: [0, PAN_STEP_PX],
  ArrowDown: [0, -PAN_STEP_PX],
};
const KEY_ZOOM: Record<string, number> = { "+": ZOOM_STEP, "=": ZOOM_STEP, "-": -ZOOM_STEP };
// Browser shortcuts (Ctrl/Cmd +/- page zoom, Alt+Arrow history) stay the browser's.
const hasCommandModifier = (e: { ctrlKey: boolean; metaKey: boolean; altKey: boolean }) =>
  e.ctrlKey || e.metaKey || e.altKey;

/** PRD 18.3 S-04 "World with HUD" centre stage: mounts a PixiJS v8
 * Application that fills and resizes with the stage at devicePixelRatio. The
 * camera is applied inside Pixi to the world (grid) position and scale. Its
 * easing is the CSS transition on the camera layer (320ms, 0 under reduced
 * motion); Pixi mirrors that layer's computed transform only while a camera
 * move or resize is under way (HR-2: nothing renders when idle). */
export function Stage() {
  const frameRef = useRef<HTMLDivElement>(null);
  const cameraElRef = useRef<HTMLDivElement>(null);
  const [supported] = useState(hasWebgl2);
  const [camera, setCamera] = useState<CameraState>(INITIAL_CAMERA);
  const dragStart = useRef<{ x: number; y: number; cam: CameraState } | null>(null);
  const followRef = useRef<((ms: number) => void) | null>(null);
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const durationMs = getCameraPanDurationMs(reducedMotion);

  useEffect(() => {
    if (!supported || !frameRef.current) return;
    const target = frameRef.current;
    const app = new Application();
    const grid = new Graphics();
    let cancelled = false;
    let mounted = false;
    let observer: ResizeObserver | undefined;
    let raf = 0;
    // `{ removeView: true }`, not `true`: `true` also releases Pixi's global
    // pools, which another live Application (StrictMode's remount) still uses.
    const destroyApp = () => app.destroy({ removeView: true }, { children: true });

    // Pixi v8's `Application.destroy` reaches into `this.renderer`, which is
    // `undefined` until `init()` resolves — calling it any earlier throws. So
    // the *first* destroy (if any) always happens inside this `.then`, either
    // because the effect was cancelled before init finished (below) or, on an
    // ordinary unmount after init resolved, from the cleanup's own `.then` on
    // this same promise (which Promise semantics guarantee runs after this
    // one). Either way `app.destroy` is called at most once.
    const initDone = app
      .init({
        backgroundColor: Number.parseInt(tokens.color.surface["0"].slice(1), 16),
        antialias: true,
        resolution: window.devicePixelRatio || 1,
        autoDensity: true,
        preference: "webgl",
        preserveDrawingBuffer: true,
      })
      .then(() => {
        if (cancelled) {
          destroyApp();
          return;
        }
        mounted = true;
        app.ticker.stop();
        target.prepend(app.canvas);
        app.stage.addChild(grid);
        const gridColor = Number.parseInt(tokens.color.ink["2"].slice(1), 16);
        const sync = () => {
          const { clientWidth: w, clientHeight: h } = target;
          if (w === 0 || h === 0) return;
          const cam = cameraElRef.current;
          const { a, e, f } = parseCameraMatrix(cam ? getComputedStyle(cam).transform : "none");
          grid.x = w / 2 + e;
          grid.y = h / 2 + f;
          grid.scale = a;
          drawIsoGrid(
            grid,
            (-w / 2 - e) / a,
            (-h / 2 - f) / a,
            (w / 2 - e) / a,
            (h / 2 - f) / a,
            gridColor,
          );
          app.renderer.render(app.stage);
        };
        // Render every frame until the camera transition (plus a frame of
        // slack) has finished, then stop.
        let until = 0;
        const follow = (ms: number) => {
          until = performance.now() + ms + 50;
          if (raf) return;
          const step = () => {
            sync();
            raf = performance.now() < until ? requestAnimationFrame(step) : 0;
          };
          step();
        };
        followRef.current = follow;
        const resize = () => {
          const { clientWidth: w, clientHeight: h } = target;
          if (w > 0 && h > 0) app.renderer.resize(w, h);
          sync();
        };
        observer = new ResizeObserver(resize);
        observer.observe(target);
        resize();
      });

    return () => {
      cancelled = true;
      followRef.current = null;
      observer?.disconnect();
      if (raf) cancelAnimationFrame(raf);
      // If init already resolved and mounted the app, this `.then` runs on
      // the next microtask and does the (only) destroy. If init hasn't
      // resolved yet, the branch above does it once `cancelled` is seen, and
      // `mounted` is left false so this is a no-op.
      initDone.then(() => {
        if (mounted) destroyApp();
      });
    };
  }, [supported]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: a camera change is the trigger; Pixi reads the resulting CSS transform.
  useEffect(() => {
    followRef.current?.(durationMs);
  }, [camera, durationMs]);

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    // React attaches JSX `onWheel` as a passive listener, so `preventDefault`
    // inside it is a no-op that also logs a console error in Chromium/Edge.
    // A native listener registered with `{ passive: false }` is required to
    // actually block the browser's default page-zoom/scroll on wheel.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setCamera((c) => zoomCamera(c, e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  return (
    <main
      className="stage-frame"
      data-testid="stage-frame"
      aria-label="World stage"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: the stage is a keyboard-pannable canvas region (PRD 9.7).
      tabIndex={0}
      ref={frameRef}
      onKeyDown={(e) => {
        if (hasCommandModifier(e)) return;
        const pan = KEY_PAN[e.key];
        const zoom = KEY_ZOOM[e.key];
        if (pan) setCamera((c) => panCamera(c, ...pan));
        else if (zoom !== undefined) setCamera((c) => zoomCamera(c, zoom));
        else return;
        e.preventDefault();
      }}
      onPointerDown={(e) => {
        dragStart.current = { x: e.clientX, y: e.clientY, cam: camera };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        const start = dragStart.current;
        if (!start) return;
        setCamera({
          ...start.cam,
          x: start.cam.x + (e.clientX - start.x),
          y: start.cam.y + (e.clientY - start.y),
        });
      }}
      onPointerUp={() => {
        dragStart.current = null;
      }}
      onPointerCancel={() => {
        dragStart.current = null;
      }}
    >
      {supported ? (
        <div
          ref={cameraElRef}
          data-testid="camera"
          className="stage-camera"
          aria-hidden="true"
          style={{
            transform: cameraTransform(camera),
            transitionDuration: `${durationMs}ms`,
          }}
        />
      ) : (
        <div className="stage-fallback" data-testid="stage-fallback">
          <p>
            This browser can't render the isometric World here. The Story lens will show the run in
            plain language instead — every card still works.
          </p>
        </div>
      )}
    </main>
  );
}
