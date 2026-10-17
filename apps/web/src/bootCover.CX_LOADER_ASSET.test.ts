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
  // FT-PERF-2: release when the app is ready, minimum 1.2 s
  await vi.advanceTimersByTimeAsync(1199);
  expect(document.getElementById("tilo-boot-cover")?.className).not.toContain("leaving");
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(true);
  await vi.advanceTimersByTimeAsync(1);
  expect(document.getElementById("tilo-boot-cover")?.className).toContain("leaving");
  expect(document.getElementById("root")?.hasAttribute("inert")).toBe(false);
});

it("FT_PERF_2_boot_cover_holds_if_app_is_not_yet_ready_at_1_2s", async () => {
  vi.useFakeTimers();
  document.body.innerHTML =
    '<div id="tilo-boot-cover"><img src="/loader/pool.webp"></div><div id="root" inert aria-hidden="true"></div>';
  const img = document.querySelector("img") as HTMLImageElement;
  img.decode = vi.fn(async () => undefined);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  installBootCover();
  const root = document.getElementById("root") as HTMLElement;

  // Past 1.2s, but app is not ready yet
  await vi.advanceTimersByTimeAsync(2000);
  expect(document.getElementById("tilo-boot-cover")?.className).not.toContain("leaving");

  // When app becomes ready, cover releases immediately
  root.innerHTML = '<main data-boot-ready="true">Ready</main>';
  await Promise.resolve();
  expect(document.getElementById("tilo-boot-cover")?.className).toContain("leaving");
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
