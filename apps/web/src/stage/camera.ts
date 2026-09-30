// Pure camera maths for the stage (PRD 9.7, HR-3). Stage.tsx applies the result to a Pixi
// world container: position = stage centre + (x, y), scale = zoom.

// PRD 18.2 "Motion": 320 ms camera (BQ-10: PRD wins over the exports' 650 ms).
export const CAMERA_PAN_MS = 320;
export const PAN_STEP_PX = 48;
export const ZOOM_STEP = 0.1;
export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 2;
/** Trackpad pinch (ctrl + wheel) zoom per px of deltaY. Windows also sends a mouse
 * Ctrl + notch as ctrl + wheel, so a 100 px event is one ZOOM_STEP and never more (C3). */
export const PINCH_ZOOM_PER_PX = ZOOM_STEP / 100;

/** x, y: screen-px offset of the world origin from the stage centre; zoom: world scale. */
export type CameraState = { x: number; y: number; zoom: number };
export const INITIAL_CAMERA: CameraState = { x: 0, y: 0, zoom: 1 };

export const getCameraPanDurationMs = (reducedMotion: boolean) =>
  reducedMotion ? 0 : CAMERA_PAN_MS;

const clampZoom = (z: number) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));

export const panCamera = (s: CameraState, dx: number, dy: number): CameraState => ({
  ...s,
  x: s.x + dx,
  y: s.y + dy,
});

export const zoomCamera = (s: CameraState, delta: number): CameraState => ({
  ...s,
  zoom: clampZoom(s.zoom + delta),
});

/** Zooms by `delta` (clamped) about the screen point (px, py), an offset from the stage
 * centre, so the world point under it stays under it. */
export function zoomAt(s: CameraState, delta: number, px: number, py: number): CameraState {
  const zoom = clampZoom(s.zoom + delta);
  const k = zoom / s.zoom;
  return { x: px - (px - s.x) * k, y: py - (py - s.y) * k, zoom };
}

export type WheelInput = {
  deltaX: number;
  deltaY: number;
  deltaMode: number;
  ctrlKey: boolean;
  shiftKey: boolean;
};
export type WheelNormalized = { panDx: number; panDy: number; zoomDelta: number };

/** deltaMode 0/1/2 (px/line/page) scale to px by 1/40/800. ctrl + wheel (trackpad pinch)
 * zooms in proportion to deltaY, at most one ZOOM_STEP per event, and never pans. Horizontal
 * intent (deltaX, or Shift + a vertical wheel) pans and never zooms. A plain vertical wheel zooms one ZOOM_STEP per
 * 100 px notch, proportionally less for smaller deltas, never more than a step per event. */
export function normalizeWheel(e: WheelInput): WheelNormalized {
  const k = [1, 40, 800][e.deltaMode] ?? 1;
  const dx = e.deltaX * k;
  const dy = e.deltaY * k;
  const capStep = (z: number) => Math.min(ZOOM_STEP, Math.max(-ZOOM_STEP, z));
  if (e.ctrlKey) return { panDx: 0, panDy: 0, zoomDelta: capStep((0 - dy) * PINCH_ZOOM_PER_PX) };
  if (dx !== 0) return { panDx: 0 - dx, panDy: 0 - dy, zoomDelta: 0 };
  if (e.shiftKey) return { panDx: 0 - dy, panDy: 0, zoomDelta: 0 };
  const steps = Math.min(1, Math.max(-1, (0 - dy) / 100));
  return { panDx: 0, panDy: 0, zoomDelta: steps * ZOOM_STEP };
}

/** Eased keyboard moves (PRD 18.2): the camera `t` of the way (0..1) from `a` to `b`, ease-out
 * cubic; t >= 1 returns `b` exactly so a move always settles on its target. */
export function easeCamera(a: CameraState, b: CameraState, t: number): CameraState {
  if (t >= 1) return b;
  const e = 1 - (1 - Math.max(0, t)) ** 3;
  return {
    x: a.x + (b.x - a.x) * e,
    y: a.y + (b.y - a.y) * e,
    zoom: a.zoom + (b.zoom - a.zoom) * e,
  };
}
