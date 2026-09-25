// PRD 18.2 "Motion" (BQ-10: PRD's 320ms wins over the exports' 650ms). Camera
// state is plain data driven by pointer/wheel/keyboard input; the CSS
// `transition` on the camera element does the easing, so nothing redraws on
// its own (HR-2: no idle animation).
export const CAMERA_PAN_MS = 320;
export const PAN_STEP_PX = 48;
export const ZOOM_STEP = 0.1;
export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 2;

export interface CameraState {
  x: number;
  y: number;
  zoom: number;
}

export const INITIAL_CAMERA: CameraState = { x: 0, y: 0, zoom: 1 };

/** PRD 18.2 "Motion: ... 320ms camera; ... reduced motion respected." */
export const getCameraPanDurationMs = (reducedMotion: boolean): number =>
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

export const cameraTransform = (s: CameraState): string =>
  `translate(${s.x}px, ${s.y}px) scale(${s.zoom})`;
