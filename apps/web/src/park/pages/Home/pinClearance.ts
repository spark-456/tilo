export interface PinRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** Find the nearest clear position using measured panels, not fixed hero heights. */
export function clearPin(card: PinRect, bounds: PinRect, panels: readonly PinRect[]) {
  const width = card.right - card.left;
  const height = card.bottom - card.top;
  const xs = [card.left, bounds.left, bounds.right - width];
  const ys = [card.top, bounds.top, bounds.bottom - height];
  for (const panel of panels) {
    xs.push(panel.left - width - 8, panel.right + 8);
    ys.push(panel.top - height - 8, panel.bottom + 8);
  }
  let best: { x: number; y: number } | null = null;
  let distance = Number.POSITIVE_INFINITY;
  for (const left of xs) {
    for (const top of ys) {
      const right = left + width;
      const bottom = top + height;
      if (left < bounds.left || top < bounds.top || right > bounds.right || bottom > bounds.bottom)
        continue;
      if (
        panels.some(
          (p) =>
            left < p.right + 8 && right > p.left - 8 && top < p.bottom + 8 && bottom > p.top - 8,
        )
      )
        continue;
      const x = left - card.left;
      const y = top - card.top;
      const d = x * x + y * y;
      if (d < distance) {
        best = { x, y };
        distance = d;
      }
    }
  }
  return best;
}
