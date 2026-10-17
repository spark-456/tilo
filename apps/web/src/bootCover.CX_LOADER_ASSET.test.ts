// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { installBootCover } from "./bootCover";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

it("CX_LOADER_ASSET_keeps_first_paint_covered_until_app_and_full_loop_are_ready", async () => {
  vi.useFakeTimers();
  document.body.innerHTML =
    '<div id="tilo-boot-cover"><img src="/loader/pool.webp"></div><div id="root" inert aria-hidden="true"></div>';
  const img = document.querySelector("img") as HTMLImageElement;
  img.decode = vi.fn(async () => undefined);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  installBootCover();
  const root = document.getElementById("root") as HTMLElement;
  root.innerHTML = '<main data-boot-ready="true">Ready</main>';
  await Promise.resolve();
  await vi.advanceTimersByTimeAsync(4599);
  expect(document.getElementById("tilo-boot-cover")?.className).not.toContain("leaving");
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(true);
  await vi.advanceTimersByTimeAsync(1);
  expect(document.getElementById("tilo-boot-cover")?.className).toContain("leaving");
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(false);
});

it("CX_LOADER_ASSET_loads_app_code_even_when_image_decode_never_settles", async () => {
  vi.useFakeTimers();
  document.body.innerHTML =
    '<div id="tilo-boot-cover"><img src="/loader/pool.webp"></div><div id="root" inert aria-hidden="true"></div>';
  const img = document.querySelector("img") as HTMLImageElement;
  img.decode = vi.fn(() => new Promise<void>(() => undefined));
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  let released = false;
  void installBootCover().then(() => {
    released = true;
  });
  await vi.advanceTimersByTimeAsync(799);
  expect(released).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  expect(released).toBe(true);
});
