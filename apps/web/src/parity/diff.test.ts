// WEB-PARITY: unit tests of the pixel-diff module (pure functions over PNG buffers).
import { PNG } from "pngjs";
import { describe, expect, it } from "vitest";
import { crop, decode, diffImages, encode, gridRects } from "../../e2e/park/parity/diff";
import { compareStyles } from "../../e2e/park/parity/styles";
import { renderMarkdown, type CaptureResult } from "../../e2e/park/parity/report";

function solid(w: number, h: number, rgba: [number, number, number, number]): PNG {
  const png = new PNG({ width: w, height: h });
  for (let i = 0; i < w * h; i++) png.data.set(rgba, i * 4);
  return png;
}

describe("WEB_PARITY diff", () => {
  it("WEB_PARITY an image diffed against itself is 0%", () => {
    const a = decode(encode(solid(20, 10, [10, 120, 200, 255])));
    const r = diffImages(a, a);
    expect([r.mismatched, r.pct, r.sizeMismatch]).toEqual([0, 0, false]);
  });

  it("WEB_PARITY one changed pixel is 1 of total", () => {
    const a = solid(10, 10, [255, 255, 255, 255]);
    const b = solid(10, 10, [255, 255, 255, 255]);
    b.data.set([0, 0, 0, 255], 4 * 13);
    const r = diffImages(a, b);
    expect(r.mismatched).toBe(1);
    expect(r.pct).toBeCloseTo(1, 5);
  });

  it("WEB_PARITY different sizes are padded to the larger, marked, and reported", () => {
    const r = diffImages(solid(10, 10, [255, 255, 255, 255]), solid(10, 20, [255, 255, 255, 255]));
    expect(r.sizeMismatch).toBe(true);
    expect([r.total, r.mismatched]).toEqual([200, 100]);
    expect(Array.from(r.padded[0].data.slice(15 * 10 * 4, 15 * 10 * 4 + 4))).toEqual([
      255, 0, 255, 255,
    ]);
  });

  it("WEB_PARITY the default 3x3 grid covers the canvas exactly", () => {
    const rects = gridRects(1440, 2201);
    expect(rects).toHaveLength(9);
    expect(rects.reduce((n, r) => n + r.w * r.h, 0)).toBe(1440 * 2201);
  });

  it("WEB_PARITY crop clamps to the image", () => {
    const c = crop(solid(10, 10, [0, 0, 0, 255]), { x: 8, y: 8, w: 50, h: 50 });
    expect([c.width, c.height]).toEqual([2, 2]);
  });

  it("WEB_PARITY the report puts the summary table first and lists console errors", () => {
    const row = (
      page: string,
      status: CaptureResult["status"],
      errs: string[] = [],
    ): CaptureResult => ({
      page,
      viewport: "1440",
      theme: "day",
      status,
      pct: 1.5,
      regions: [],
      consoleErrors: errs,
      dir: `${page}/1440-day`,
    });
    const md = renderMarkdown([row("team", "route missing"), row("home", "ok", ["[error] boom"])]);
    expect(md.indexOf("| Page |")).toBeLessThan(md.indexOf("## Captures"));
    expect(md).toContain("route missing");
    expect(md).toContain("- [error] boom");
  });

  it("WEB_PARITY computed styles: equal is no rows, a different property is one row", () => {
    const n = (fontSize: string) => ({
      label: "h1",
      tag: "H1",
      styles: { fontSize, color: "red" },
    });
    expect(compareStyles("r", [n("36px")], [n("36px")])).toEqual([]);
    expect(compareStyles("r", [n("36px")], [n("32px")])).toEqual([
      { region: "r", element: "h1", prop: "fontSize", design: "36px", ours: "32px" },
    ]);
  });
});
