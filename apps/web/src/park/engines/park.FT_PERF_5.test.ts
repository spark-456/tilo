// FT-PERF-5: generated Park SVGs are already in memory. Serving them as data URLs avoids
// hundreds of blob resource loads on Home, and route-specific font preloads avoid warnings.
import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { createPark } from "./park";
import type { H } from "./types";
import { createWorld } from "./world";

const h: H = (tag, props, ...children) => ({ tag, props, children }) as never;
const srcOf = (node: unknown): string =>
  String((node as { props?: { src?: string } }).props?.src ?? "");

describe("FT_PERF_5 generated art and font loading", () => {
  it("FT_PERF_5 keeps generated SVG art out of the blob request list", () => {
    const create = vi.spyOn(URL, "createObjectURL").mockImplementation(() => {
      throw new Error("generated Park art must not create a blob URL");
    });
    const park = createPark(h, createWorld);

    expect(srcOf(park.agent({ role: "builder", expr: "focused" }, 48, false))).toMatch(
      /^data:image\/svg\+xml,/,
    );
    expect(create).not.toHaveBeenCalled();
  });

  it("FT_PERF_5 does not preload route-specific fonts from the shared HTML", () => {
    const config = readFileSync(new URL("../../../vite.config.ts", import.meta.url), "utf8");

    expect(config).not.toContain("tilo-preload-fonts");
    expect(config).not.toMatch(/rel:\s*["']preload["'][\s\S]{0,120}as:\s*["']font["']/);
  });
});
