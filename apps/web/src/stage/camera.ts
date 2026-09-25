// PRD 18.2 "Motion": 320 ms camera (BQ-10: PRD wins over the exports' 650 ms).
export const CAMERA_PAN_MS = 320;
export const PAN_STEP_PX = 48;
export const ZOOM_STEP = 0.1;
export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 2;

export type CameraState = { x: number; y: number; zoom: number };
export const INITIAL_CAMERA: CameraState = { x: 0, y: 0, zoom: 1 };

export const getCameraPanDurationMs = (reducedMotion: boolean) =>
  reducedMotion ? 0 : CAMERA_PAN_MS;

export const panCamera = (s: CameraState, dx: number, dy: number): CameraState => ({
  ...s,
  x: s.x + dx,
  y: s.y + dy,
});

export const zoomCamera = (s: CameraState, delta: number): CameraState => ({
  ...s,
  zoom: Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, s.zoom + delta)),
});

/** A 100 px wheel notch zooms one ZOOM_STEP; smaller (trackpad) deltas zoom proportionally
 * less; one event never exceeds a step. deltaMode 1 is lines, 2 is pages. */
export const wheelZoomDelta = (deltaY: number, deltaMode = 0) => {
  const steps = (-deltaY * ([1, 40, 800][deltaMode] ?? 1)) / 100;
  return Math.min(1, Math.max(-1, steps)) * ZOOM_STEP;
};

export const cameraTransform = (s: CameraState) => `translate(${s.x}px, ${s.y}px) scale(${s.zoom})`;
