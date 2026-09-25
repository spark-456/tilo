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

// PRD 9.1/9.7: a static isometric grid, tile size from the design tokens.
function drawIsoGrid(g: Graphics, width: number, height: number, color: number): void {
  g.clear();
  const { tileWidth: tw, tileHeight: th } = tokens.stage;
  const cols = Math.ceil(width / tw) + 2;
  const rows = Math.ceil(height / th) + 2;
  const cx = width / 2;
  const cy = height / 2;
  for (let i = -rows; i <= rows; i++) {
    for (let j = -cols; j <= cols; j++) {
      const x = cx + (i - j) * (tw / 2);
      const y = cy + (i + j) * (th / 2);
      if (x < -tw || x > width + tw || y < -th || y > height + th) continue;
      g.moveTo(x, y - th / 2)
        .lineTo(x + tw / 2, y)
        .lineTo(x, y + th / 2)
        .lineTo(x - tw / 2, y)
        .closePath();
    }
  }
  g.stroke({ width: 1, color, alpha: 0.35 });
}

const KEY_PAN: Record<string, [number, number]> = {
  ArrowLeft: [PAN_STEP_PX, 0],
  ArrowRight: [-PAN_STEP_PX, 0],
  ArrowUp: [0, PAN_STEP_PX],
  ArrowDown: [0, -PAN_STEP_PX],
};
const KEY_ZOOM: Record<string, number> = { "+": ZOOM_STEP, "=": ZOOM_STEP, "-": -ZOOM_STEP };

/** PRD 18.3 S-04 "World with HUD" centre stage: mounts a PixiJS v8
 * Application that fills and resizes with the stage, draws the static iso
 * grid once (HR-2: the render loop stops after the first frame and only
 * re-fires on an actual resize), and supports camera pan/zoom by pointer and
 * keyboard at the PRD 18.2 motion duration. */
export function Stage() {
  const frameRef = useRef<HTMLDivElement>(null);
  const cameraElRef = useRef<HTMLDivElement>(null);
  const [supported] = useState(hasWebgl2);
  const [camera, setCamera] = useState<CameraState>(INITIAL_CAMERA);
  const dragStart = useRef<{ x: number; y: number; cam: CameraState } | null>(null);
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");

  useEffect(() => {
    if (!supported || !cameraElRef.current || !frameRef.current) return;
    const target = frameRef.current;
    const app = new Application();
    const grid = new Graphics();
    let cancelled = false;
    let observer: ResizeObserver | undefined;

    app
      .init({
        backgroundColor: Number.parseInt(tokens.color.surface["0"].slice(1), 16),
        antialias: true,
        preference: "webgl",
      })
      .then(() => {
        if (cancelled || !cameraElRef.current) {
          app.destroy(true);
          return;
        }
        app.ticker.stop();
        cameraElRef.current.appendChild(app.canvas);
        app.stage.addChild(grid);
        const gridColor = Number.parseInt(tokens.color.ink["2"].slice(1), 16);
        const resize = () => {
          const { clientWidth: w, clientHeight: h } = target;
          if (w === 0 || h === 0) return;
          app.renderer.resize(w, h);
          drawIsoGrid(grid, w, h, gridColor);
          app.renderer.render(app.stage);
        };
        resize();
        observer = new ResizeObserver(resize);
        observer.observe(target);
      });

    return () => {
      cancelled = true;
      observer?.disconnect();
      app.destroy(true, { children: true });
    };
  }, [supported]);

  return (
    <main
      className="stage-frame"
      data-testid="stage-frame"
      aria-label="World stage"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: the stage is a keyboard-pannable canvas region (PRD 9.7).
      tabIndex={0}
      ref={frameRef}
      onKeyDown={(e) => {
        const pan = KEY_PAN[e.key];
        const zoom = KEY_ZOOM[e.key];
        if (pan) setCamera((c) => panCamera(c, ...pan));
        else if (zoom !== undefined) setCamera((c) => zoomCamera(c, zoom));
        else return;
        e.preventDefault();
      }}
      onWheel={(e) => {
        e.preventDefault();
        setCamera((c) => zoomCamera(c, e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP));
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
          style={{
            transform: cameraTransform(camera),
            transitionDuration: `${getCameraPanDurationMs(reducedMotion)}ms`,
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
