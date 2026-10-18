// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { installBootCover } from "./bootCover";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  document.documentElement.classList.remove("tilo-returning-session");
  document.body.innerHTML = "";
});

it("R_LOADER_keeps_first_visit_covered_until_the_4_6_second_loop_and_app_are_ready", async () => {
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

it("R_LOADER_holds_after_the_first_loop_until_the_app_is_ready", async () => {
  vi.useFakeTimers();
  document.body.innerHTML =
    '<div id="tilo-boot-cover"><img src="/loader/pool.webp"></div><div id="root" inert aria-hidden="true"></div>';
  const img = document.querySelector("img") as HTMLImageElement;
  img.decode = vi.fn(async () => undefined);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  installBootCover();
  const root = document.getElementById("root") as HTMLElement;

  await vi.advanceTimersByTimeAsync(5000);
  expect(document.getElementById("tilo-boot-cover")?.className).not.toContain("leaving");

  // When app becomes ready, cover releases immediately
  root.innerHTML = '<main data-boot-ready="true">Ready</main>';
  await Promise.resolve();
  expect(document.getElementById("tilo-boot-cover")?.className).toContain("leaving");
});

it("R_LOADER_keeps_a_returning_visit_hidden_until_loading_exceeds_300ms", async () => {
  vi.useFakeTimers();
  window.sessionStorage.setItem("tilo-boot-seen", "1");
  document.documentElement.classList.add("tilo-returning-session");
  document.body.innerHTML =
    '<div id="tilo-boot-cover"><img src="/loader/pool.webp"></div><div id="root" inert aria-hidden="true"></div>';
  const img = document.querySelector("img") as HTMLImageElement;
  img.decode = vi.fn(async () => undefined);
  vi.stubGlobal("matchMedia", () => ({ matches: false }));

  installBootCover();
  await vi.advanceTimersByTimeAsync(299);
  expect(document.documentElement.classList).toContain("tilo-returning-session");
  await vi.advanceTimersByTimeAsync(1);
  expect(document.documentElement.classList).not.toContain("tilo-returning-session");
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
