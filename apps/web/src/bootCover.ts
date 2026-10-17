const DECODE_WAIT_MS = 800;
/** FT-PERF-2: release when the app is ready, minimum 1.2 s */
const MIN_BOOT_WAIT_MS = 1200;

/** The HTML cover exists before the JavaScript bundle. Release it after the app and one saved loop are ready. */
export function installBootCover(): Promise<void> {
  const cover = document.getElementById("tilo-boot-cover");
  const root = document.getElementById("root");
  const image = cover?.querySelector("img");
  if (!cover || !root || !image) return Promise.resolve();

  let appReady = false;
  let loopReady = false;
  const reveal = () => {
    if (!appReady || !loopReady) return;
    observer.disconnect();
    root.removeAttribute("inert");
    root.removeAttribute("aria-hidden");
    cover.classList.add("tilo-boot-cover--leaving");
    window.setTimeout(() => cover.remove(), 300);
  };
  const check = () => {
    appReady = Boolean(
      root.querySelector(
        '[data-testid="sign-in"], [data-testid^="legal-"], [data-testid="oauth-callback"], [data-boot-ready="true"]',
      ),
    );
    reveal();
  };
  const observer = new MutationObserver(check);
  observer.observe(root, { childList: true, subtree: true, attributes: true });
  check();

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The loop plays once per browser session; a later load only waits for the app (the cover is decoration).
  let seen = false;
  try {
    seen = window.sessionStorage.getItem("tilo-boot-seen") === "1";
    window.sessionStorage.setItem("tilo-boot-seen", "1");
  } catch {
    // storage blocked: play the loop
  }
  // Resolves once the cover artwork is decoded (the cover is drawn), so the caller can load app code after it.
  // `decode()` of an animated image can stay pending (seen in embedded Chromium), which would hold the app back for
  // good: the cover waits for it at most DECODE_WAIT_MS, then app code loads anyway.
  const decoded = Promise.race([
    image.decode().catch(() => undefined),
    new Promise<void>((resolve) => window.setTimeout(resolve, DECODE_WAIT_MS)),
  ]);
  void decoded.then(() => {
    window.setTimeout(
      () => {
        loopReady = true;
        cover.dataset.loopComplete = "true";
        image.src = "/loader/pool-576f781839ee.png";
        window.dispatchEvent(new Event("tilo-boot-loop-complete"));
        reveal();
      },
      reduced || seen ? 200 : MIN_BOOT_WAIT_MS,
    );
  });
  return decoded;
}
