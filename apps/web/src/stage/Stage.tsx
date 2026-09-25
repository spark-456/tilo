import { Application, Graphics } from "pixi.js";
import { useEffect, useRef, useState } from "react";
import tokens from "../design/tokens";
import { useMediaQuery } from "../hooks/useMediaQuery";
import * as cam from "./camera";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;
const PIXI = { autoDensity: true, autoStart: false, preserveDrawingBuffer: true } as const;

// Iso lattice: lines of slope +-TH/TW, TH apart, through (0, -TH/2), across the visible rect.
function drawIsoGrid(g: Graphics, x0: number, y0: number, x1: number, y1: number) {
  g.clear();
  for (const m of [TH / TW, -TH / TW]) {
    const hi = Math.max(y1 - m * x0, y1 - m * x1) + TH / 2;
    const lo = Math.min(y0 - m * x0, y0 - m * x1) + TH / 2;
    for (let c = Math.floor(lo / TH) * TH - TH / 2; c <= hi; c += TH) {
      g.moveTo(x0, m * x0 + c).lineTo(x1, m * x1 + c);
    }
  }
  g.stroke({ width: 1, color: tokens.color.ink["2"], alpha: 0.35, pixelLine: true });
}

const { PAN_STEP_PX: P, ZOOM_STEP: Z, panCamera: pan, zoomCamera: zoom } = cam;
const KEYS: Record<string, (c: cam.CameraState) => cam.CameraState> = {
  ArrowLeft: (c) => pan(c, P, 0),
  ArrowRight: (c) => pan(c, -P, 0),
  ArrowUp: (c) => pan(c, 0, P),
  ArrowDown: (c) => pan(c, 0, -P),
  "+": (c) => zoom(c, Z),
  "=": (c) => zoom(c, Z),
  "-": (c) => zoom(c, -Z),
};

/** PRD 18.3 S-04 stage: Pixi mirrors the camera layer's eased CSS transform only while it moves. */
export function Stage() {
  const frameRef = useRef<HTMLElement>(null);
  const cameraRef = useRef<HTMLDivElement>(null);
  const followRef = useRef<((ms: number) => void) | null>(null);
  const [supported] = useState(() => !!document.createElement("canvas").getContext("webgl2"));
  const [camera, setCamera] = useState(cam.INITIAL_CAMERA);
  const ms = cam.getCameraPanDurationMs(useMediaQuery("(prefers-reduced-motion: reduce)"));

  useEffect(() => {
    const target = frameRef.current;
    if (!supported || !target) return;
    // Ctrl/Cmd/Alt shortcuts stay the browser's; element `onwheel` is not passive.
    let last: [number, number] = [0, 0];
    target.onkeydown = (e) => {
      const move = KEYS[e.key];
      if (!move || e.ctrlKey || e.metaKey || e.altKey) return;
      e.preventDefault();
      setCamera(move);
    };
    target.onpointerdown = (e) => {
      last = [e.clientX, e.clientY];
    };
    target.onpointermove = (e) => {
      const [dx, dy] = [e.clientX - last[0], e.clientY - last[1]];
      last = [e.clientX, e.clientY];
      if (e.buttons === 1) setCamera((c) => pan(c, dx, dy));
    };
    target.onwheel = (e) => {
      e.preventDefault();
      if (e.deltaY) setCamera((c) => zoom(c, cam.wheelZoomDelta(e.deltaY, e.deltaMode)));
    };

    const app = new Application();
    const grid = new Graphics();
    let cancelled = false;
    let timer = 0;
    const sync = () => {
      const { clientWidth: w, clientHeight: h } = target;
      if (!w || !h || !cameraRef.current) return;
      const { a, e, f } = new DOMMatrix(getComputedStyle(cameraRef.current).transform);
      grid.position.set(w / 2 + e, h / 2 + f);
      grid.scale = a;
      drawIsoGrid(grid, (-w / 2 - e) / a, (-h / 2 - f) / a, (w / 2 - e) / a, (h / 2 - f) / a);
    };
    // The device-pixel box also reports devicePixelRatio changes, keeping the canvas sharp.
    const observer = new ResizeObserver(() => {
      app.renderer.resize(target.clientWidth || 1, target.clientHeight || 1, devicePixelRatio);
      sync();
      app.render();
    });
    const ready = app.init({ ...PIXI, background: tokens.color.surface["0"] });
    ready.then(() => {
      if (cancelled) return;
      target.prepend(app.canvas);
      app.stage.addChild(grid);
      app.ticker.add(sync); // the ticker runs only while the camera moves
      // Stop only once no transition runs, after one last sync+render of the settled transform
      // (a late timer after a long task or in a hidden tab must not freeze a mid-pan frame).
      const settle = () => {
        if (cameraRef.current?.getAnimations().length) {
          timer = window.setTimeout(settle, 50);
          return;
        }
        app.ticker.stop();
        sync();
        app.render();
      };
      followRef.current = (duration) => {
        app.ticker.start();
        clearTimeout(timer);
        timer = window.setTimeout(settle, duration + 50);
      };
      const box = "devicePixelContentBoxSize" in ResizeObserverEntry.prototype;
      observer.observe(target, box ? { box: "device-pixel-content-box" } : {});
    });
    return () => {
      cancelled = true;
      followRef.current = null;
      observer.disconnect();
      clearTimeout(timer);
      // Pixi's destroy() throws before init() resolves, so it always waits for init.
      ready.then(() => app.destroy({ removeView: true }, { children: true }));
    };
  }, [supported]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: a camera change is the trigger.
  useEffect(() => followRef.current?.(ms), [camera, ms]);

  return (
    <main
      className="stage-frame"
      data-testid="stage-frame"
      aria-label="World stage"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard pan and zoom (PRD 9.7).
      tabIndex={0}
      ref={frameRef}
    >
      {supported ? (
        <div
          ref={cameraRef}
          data-testid="camera"
          className="stage-camera"
          aria-hidden="true"
          style={{ transform: cam.cameraTransform(camera), transitionDuration: `${ms}ms` }}
        />
      ) : (
        <p className="stage-fallback" data-testid="stage-fallback">
          This browser can't render the isometric World. The Story lens will show the run instead.
        </p>
      )}
    </main>
  );
}
