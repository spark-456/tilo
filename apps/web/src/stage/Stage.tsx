import type { Layout } from "@tilo/contracts";
import type { Container, Graphics } from "pixi.js";
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import tokens from "../design/tokens";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { AppLink } from "../screens/AppLink";
import { agentNames, rankName } from "../world/runSummary";
import { useSelection } from "../world/selection";
import * as cam from "./camera";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;
const BARE_GRID_DELAY_MS = 1500;
const PIXI = { autoDensity: true, autoStart: false, preserveDrawingBuffer: true } as const;

// Iso lattice in world coordinates: lines of slope +-TH/TW, TH apart, through (0, -TH/2),
// across the visible world rect (so the grid is anchored to the world, never to the screen).
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

const { PAN_STEP_PX: P, ZOOM_STEP: Z, panCamera: pan, zoomAt } = cam;
// Keyboard moves start from the previous move's target, so rapid presses never drift.
const KEYS: Record<string, (c: cam.CameraState) => cam.CameraState> = {
  ArrowLeft: (c) => pan(c, P, 0),
  ArrowRight: (c) => pan(c, -P, 0),
  ArrowUp: (c) => pan(c, 0, P),
  ArrowDown: (c) => pan(c, 0, -P),
  "+": (c) => zoomAt(c, Z, 0, 0),
  "=": (c) => zoomAt(c, Z, 0, 0),
  "-": (c) => zoomAt(c, -Z, 0, 0),
};

/**
 * World content seam: called once the renderer is ready with the Pixi world container (the
 * camera's transform; the iso grid is its first child) and `requestRender`, which draws one
 * frame on demand (there is no always-on ticker, HR-2), and `size`, the stage's current pixel size
 * (the world frames itself in it once). May return a cleanup function.
 */
export type WorldSeam = (
  world: Container,
  requestRender: () => void,
  size: () => { width: number; height: number },
) => (() => void) | undefined;

/** PRD 18.3 S-04 stage. The camera is the Pixi world container's transform (PRD 9.7); a frame
 * is drawn only on input, an eased keyboard move, resize or visibility change. Readiness: the
 * stage frame gains `data-stage-ready="true"` and `data-camera-x/-y/-zoom` with the first drawn
 * frame (right after Pixi's init), never before; input listeners attach at mount and buffer
 * input into that first frame. `seq`
 * (P0-08b-player, FR-WLD-04) is purely a display attribute for a world-content consumer's own
 * highest applied seq; Stage itself never reads or produces it. */
export function Stage({
  onWorld,
  seq,
  selected,
  paused = false,
  layout,
  worldId,
}: {
  onWorld?: WorldSeam;
  seq?: number;
  selected?: string | null;
  paused?: boolean;
  layout?: Layout | null;
  worldId?: string;
}) {
  const [, set, toggle] = useSelection(worldId ?? "");
  const outlineItems = useMemo(() => {
    if (!layout) return [];
    const names = agentNames(layout);
    const items: { id: string; name: string; inspect: boolean }[] = [];
    for (const a of layout.semantic.agents) {
      items.push({ id: a.id, name: names.get(a.id) ?? a.id, inspect: true });
    }
    for (const l of layout.semantic.levels) {
      for (const d of l.districts) {
        for (const b of d.buildings) items.push({ id: b.id, name: b.name, inspect: true });
      }
    }
    for (const g of layout.semantic.gates) {
      items.push({ id: g.id, name: `Gate ${g.id} (${rankName(g.guards)})`, inspect: false }); // a gate is not an Inspect object
    }
    return items;
  }, [layout]);

  // Roving focus: one tab stop, arrows move within the list (FR-WLD-11). Escape clears the
  // selection and leaves focus on the item, a real control.
  const [active, setActive] = useState(0);
  const outlineRef = useRef<HTMLUListElement>(null);
  const onOutlineKey = (e: KeyboardEvent<HTMLUListElement>) => {
    const buttons = [...(outlineRef.current?.querySelectorAll<HTMLElement>(".outline-item") ?? [])];
    if (e.key === "Escape") {
      // Focus goes to the roving item first: the Inspect link, if that is where it was, leaves
      // with the selection and would take focus to the page body with it.
      buttons[active]?.focus();
      return set(null);
    }
    const at = buttons.indexOf(document.activeElement as HTMLElement);
    const next =
      e.key === "ArrowDown" || e.key === "ArrowRight"
        ? Math.min(at + 1, buttons.length - 1)
        : e.key === "ArrowUp" || e.key === "ArrowLeft"
          ? Math.max(at - 1, 0)
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? buttons.length - 1
              : -1;
    if (next < 0 || at < 0) return;
    e.preventDefault();
    buttons[next]?.focus();
  };

  const frameRef = useRef<HTMLElement>(null);
  const [supported] = useState(() => !!document.createElement("canvas").getContext("webgl2"));
  const msRef = useRef(0);
  msRef.current = cam.getCameraPanDurationMs(useMediaQuery("(prefers-reduced-motion: reduce)"));
  const seamRef = useRef(onWorld);
  seamRef.current = onWorld;

  // Pixi is code-split off the landing route (NFR-01): the page is interactive without it. A world
  // to draw loads it at once; the bare grid is decoration, so it waits until the first keystroke
  // has had its turn (the Pixi script is the largest task on the page).
  const [pixi, setPixi] = useState<typeof import("pixi.js") | null>(null);
  const [loadFailed, setLoadFailed] = useState(false); // the chunk did not arrive (offline, a new deploy)
  const bare = onWorld === undefined;
  useEffect(() => {
    if (!supported) return;
    let live = true;
    const timer = setTimeout(
      () =>
        // `pixi.js/unsafe-eval` swaps Pixi's shader-sync code generators for ones that do not call
        // `new Function`, so the Hosting CSP (firebase.json, P0-07c) needs no 'unsafe-eval'.
        void Promise.all([import("pixi.js"), import("pixi.js/unsafe-eval")]).then(
          ([m]) => live && setPixi(m),
          () => live && setLoadFailed(true), // said below on a world; the bare grid just stays empty
        ),
      bare ? BARE_GRID_DELAY_MS : 0,
    );
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [supported, bare]);
  // A browser keeps a failed dynamic import for the life of the page, so a second import() never
  // reaches the network; a reload does, and also picks up a redeployed chunk's new name.
  const retryLoad = () => window.location.reload();

  useEffect(() => {
    const target = frameRef.current;
    if (!supported || !target || !pixi) return;
    const { Application, Container, Graphics } = pixi;
    const app = new Application();
    const world = new Container();
    const grid = new Graphics();
    world.addChild(grid);
    let ready = false;
    let cur = cam.INITIAL_CAMERA; // the camera drawn now
    let goal = cur; // where keyboard moves are heading
    let ease: { from: cam.CameraState; t0: number } | null = null;
    let raf = 0;
    let gridKey = ""; // the view the grid was last built for: world-content frames skip rebuilding it

    const draw = () => {
      const { clientWidth: w, clientHeight: h } = target;
      if (!ready || !w || !h) return;
      const { x, y, zoom: z } = cur;
      world.position.set(w / 2 + x, h / 2 + y);
      world.scale.set(z);
      const key = `${x},${y},${z},${w},${h}`;
      if (key !== gridKey) {
        gridKey = key;
        drawIsoGrid(grid, (-w / 2 - x) / z, (-h / 2 - y) / z, (w / 2 - x) / z, (h / 2 - y) / z);
      }
      app.render();
      target.dataset.cameraX = String(x);
      target.dataset.cameraY = String(y);
      target.dataset.cameraZoom = String(z);
      target.dataset.stageReady = "true";
    };
    // Eased moves are timed by performance.now(), so a long task or a frozen page lands on
    // the target at the next frame, and the last frame is always exactly the target.
    const frame = () => {
      raf = 0;
      if (ease) {
        const t = (performance.now() - ease.t0) / msRef.current;
        cur = cam.easeCamera(ease.from, goal, t);
        if (t >= 1) ease = null;
        else raf = requestAnimationFrame(frame);
      }
      draw();
    };
    const requestRender = () => {
      if (!raf) raf = requestAnimationFrame(frame);
    };
    // Direct manipulation follows the input with no easing.
    const jump = (next: cam.CameraState) => {
      ease = null;
      cur = goal = next;
      draw();
    };
    const glide = (next: cam.CameraState) => {
      if (!msRef.current) return jump(next);
      ease = { from: cur, t0: performance.now() };
      goal = next;
      requestRender();
    };

    const on = new AbortController();
    const listen = <K extends keyof HTMLElementEventMap>(
      type: K,
      fn: (e: HTMLElementEventMap[K]) => void,
      opts: AddEventListenerOptions = {},
    ) => target.addEventListener(type, fn, { ...opts, signal: on.signal });
    const fromCentre = (cx: number, cy: number): [number, number] => {
      const r = target.getBoundingClientRect();
      return [cx - r.left - r.width / 2, cy - r.top - r.height / 2];
    };

    // Pointers by pointerId: one pans by its own movement; two pinch about their midpoint.
    // Each gesture is measured from an anchor taken whenever the set of pointers changes,
    // so a finger landing or lifting never jumps and zoom clamping never accumulates.
    const pts = new Map<number, { x: number; y: number }>();
    const spread = () => {
      const [a, b] = [...pts.values()];
      if (!a) return { mx: 0, my: 0, d: 0 };
      if (!b) return { mx: a.x, my: a.y, d: 0 };
      return { mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2, d: Math.hypot(a.x - b.x, a.y - b.y) };
    };
    let anchor = { cam: cur, ...spread() };
    const reanchor = () => {
      anchor = { cam: cur, ...spread() };
    };
    listen("pointerdown", (e) => {
      if (e.button !== 0 || pts.size >= 2) return; // right and middle buttons never pan
      ease = null; // direct manipulation takes over from an eased keyboard move
      goal = cur;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      reanchor(); // before the capture: a throw below must not leave a stale anchor
      try {
        target.setPointerCapture?.(e.pointerId);
      } catch {
        // A synthetic or already-inactive pointer id has nothing to capture; the drag still pans.
      }
    });
    listen("pointermove", (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const { mx, my, d } = spread();
      const a = anchor.cam;
      const zoom = anchor.d > 0 ? (a.zoom * d) / anchor.d : a.zoom;
      const moved = pan(a, mx - anchor.mx, my - anchor.my);
      jump(zoomAt(moved, zoom - a.zoom, ...fromCentre(mx, my)));
    });
    const lift = (e: PointerEvent) => {
      if (pts.delete(e.pointerId)) reanchor();
    };
    listen("pointerup", lift);
    listen("pointercancel", lift);

    listen("keydown", (e) => {
      const move = KEYS[e.key];
      if (!move || e.ctrlKey || e.metaKey || e.altKey) return; // browser shortcuts pass
      if ((e.target as Element).closest(".stage-outline")) return; // arrows belong to the list
      e.preventDefault();
      if (!pts.size) glide(move(goal)); // a drag or pinch in progress owns the camera
    });
    // Native and non-passive, so preventDefault() works without a console error.
    listen(
      "wheel",
      (e) => {
        e.preventDefault();
        const n = cam.normalizeWheel(e);
        if (n.zoomDelta) jump(zoomAt(cur, n.zoomDelta, ...fromCentre(e.clientX, e.clientY)));
        else if (n.panDx || n.panDy) jump(pan(cur, n.panDx, n.panDy));
        reanchor();
      },
      { passive: false },
    );

    // The device-pixel box also reports devicePixelRatio changes, keeping the canvas sharp.
    const fit = () => {
      app.renderer.resize(target.clientWidth || 1, target.clientHeight || 1, devicePixelRatio);
      draw();
    };
    const observer = new ResizeObserver(fit);
    const onVisible = () => document.visibilityState === "visible" && draw();
    document.addEventListener("visibilitychange", onVisible, { signal: on.signal });

    let unplug: (() => void) | undefined;
    const init = app.init({ ...PIXI, background: tokens.color.surface["0"] });
    init.then(() => {
      if (on.signal.aborted) return;
      ready = true;
      target.prepend(app.canvas);
      app.stage.addChild(world);
      unplug = seamRef.current?.(world, requestRender, () => ({
        width: target.clientWidth,
        height: target.clientHeight,
      }));
      fit(); // the first frame, at once: input that arrived during init is already in `cur`
      const box = "devicePixelContentBoxSize" in ResizeObserverEntry.prototype;
      observer.observe(target, box ? { box: "device-pixel-content-box" } : {});
    });
    return () => {
      on.abort();
      observer.disconnect();
      cancelAnimationFrame(raf);
      unplug?.();
      // Pixi's destroy() throws before init() resolves, so it always waits for init.
      init.then(() => app.destroy({ removeView: true }, { children: true }));
    };
  }, [supported, pixi]);

  return (
    <main
      className="stage-frame"
      data-testid="stage-frame"
      {...(seq !== undefined ? { "data-seq": seq } : {})}
      {...(selected ? { "data-selected": selected } : {})}
      {...(paused ? { "data-paused": "true" } : {})}
      aria-label="World stage"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard pan and zoom (PRD 9.7).
      tabIndex={0}
      ref={frameRef}
    >
      {paused && (
        // FR-WLD-07: drawn only while the recorded status is "paused"; static (no animation) and
        // click-through, so the camera still pans. Its word does not rely on colour.
        <div className="world-veil" data-testid="world-veil">
          <span className="veil-label">Paused</span>
        </div>
      )}
      {loadFailed && !bare && (
        <div className="stage-fallback" data-testid="stage-load-failed" role="alert">
          <p>The world couldn't be drawn: its drawing code didn't load. Check your connection.</p>
          <button type="button" className="secondary" onClick={retryLoad}>
            Try again
          </button>
        </div>
      )}
      {!supported && (
        <p className="stage-fallback" data-testid="stage-fallback">
          This browser can't render the isometric World. The Story lens will show the run instead.
        </p>
      )}
      {outlineItems.length > 0 && (
        <ul
          className="stage-outline"
          aria-label="World objects"
          ref={outlineRef}
          onKeyDown={onOutlineKey}
        >
          {outlineItems.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                className="outline-item"
                data-lens-control
                tabIndex={i === active ? 0 : -1}
                aria-pressed={selected === item.id}
                onFocus={() => setActive(i)}
                onClick={() => toggle(item.id)}
              >
                {item.name}
              </button>
              {selected === item.id && item.inspect && worldId && (
                <AppLink
                  to={`/world/${encodeURIComponent(worldId)}/inspect/${encodeURIComponent(item.id)}`}
                >
                  Inspect
                </AppLink>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
