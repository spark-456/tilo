// FR-WLD-13: the pixel density the stage draws at. A phone canvas is small in CSS pixels but its screen is
// 3x (or more); every extra device pixel is fill cost on a mid-range GPU/CPU. Drawing a phone-width canvas at
// no more than 2x keeps it crisp (the art is vector shapes and 2x text) and cuts the pixels by 44% at 3x.
// Wider canvases keep the device ratio, so the desktop look is unchanged.
const PHONE_MAX_CSS_WIDTH = 768;
const PHONE_MAX_RESOLUTION = 2;

export function stageResolution(devicePixelRatio: number, cssWidth: number): number {
  const dpr = Number.isFinite(devicePixelRatio) && devicePixelRatio > 0 ? devicePixelRatio : 1;
  return cssWidth <= PHONE_MAX_CSS_WIDTH ? Math.min(dpr, PHONE_MAX_RESOLUTION) : dpr;
}
