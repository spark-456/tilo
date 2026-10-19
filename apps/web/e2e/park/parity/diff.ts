// WEB-PARITY: pure pixel-diff helpers over PNG buffers (dev/test tool; no browser, no I/O).
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface DiffResult {
  mismatched: number;
  total: number;
  pct: number;
  sizeA: [number, number];
  sizeB: [number, number];
  sizeMismatch: boolean;
  /** The diff image, same size as the padded canvas. */
  diff: PNG;
  /** Both images on the shared (padded) canvas. */
  padded: [PNG, PNG];
}

/** Marker colour for padding: magenta, so a size mismatch shows as a solid band, never as page colour. */
const MARKER = [255, 0, 255, 255] as const;

export const decode = (buf: Buffer): PNG => PNG.sync.read(buf);
export const encode = (png: PNG): Buffer => PNG.sync.write(png);

/** Copy of `src` on a `w` x `h` canvas (at least as large as `src`), the extra area in the marker colour. */
export function pad(src: PNG, w: number, h: number): PNG {
  const out = new PNG({ width: w, height: h });
  for (let i = 0; i < w * h; i++) out.data.set(MARKER, i * 4);
  PNG.bitblt(src, out, 0, 0, Math.min(src.width, w), Math.min(src.height, h), 0, 0);
  return out;
}

/** The part of `src` inside `r`, clamped to the image; at least 1x1. */
export function crop(src: PNG, r: Rect): PNG {
  const x = Math.max(0, Math.min(src.width - 1, Math.round(r.x)));
  const y = Math.max(0, Math.min(src.height - 1, Math.round(r.y)));
  const w = Math.max(1, Math.min(src.width - x, Math.round(r.w)));
  const h = Math.max(1, Math.min(src.height - y, Math.round(r.h)));
  const out = new PNG({ width: w, height: h });
  PNG.bitblt(src, out, x, y, w, h, 0, 0);
  return out;
}

/** Diff two images; different sizes are padded to the larger one and reported as `sizeMismatch`. */
export function diffImages(a: PNG, b: PNG): DiffResult {
  const w = Math.max(a.width, b.width);
  const h = Math.max(a.height, b.height);
  const pa = a.width === w && a.height === h ? a : pad(a, w, h);
  const pb = b.width === w && b.height === h ? b : pad(b, w, h);
  const diff = new PNG({ width: w, height: h });
  const mismatched = pixelmatch(pa.data, pb.data, diff.data, w, h, { threshold: 0.1 });
  const total = w * h;
  return {
    mismatched,
    total,
    pct: (mismatched / total) * 100,
    sizeA: [a.width, a.height],
    sizeB: [b.width, b.height],
    sizeMismatch: a.width !== b.width || a.height !== b.height,
    diff,
    padded: [pa, pb],
  };
}

/** `n` x `n` rects covering a `w` x `h` canvas exactly (the last row and column take the remainder). */
export function gridRects(w: number, h: number, n = 3): (Rect & { name: string })[] {
  const out: (Rect & { name: string })[] = [];
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const x = Math.floor((c * w) / n);
      const y = Math.floor((r * h) / n);
      out.push({
        name: `grid-r${r + 1}c${c + 1}`,
        x,
        y,
        w: Math.floor(((c + 1) * w) / n) - x,
        h: Math.floor(((r + 1) * h) / n) - y,
      });
    }
  }
  return out;
}
