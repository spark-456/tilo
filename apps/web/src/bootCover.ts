const DECODE_WAIT_MS = 800;
const FIRST_LOOP_MS = 4600;
const RETURNING_DELAY_MS = 300;
const MAX_BOOT_WAIT_MS = 6000;

/** The HTML cover exists before the JavaScript bundle. Release it as soon as the app is ready. */
export function installBootCover(): Promise<void> {
  const cover = document.getElementById("tilo-boot-cover");
  const root = document.getElementById("root");
  const image = cover?.querySelector("img");
  if (!cover || !root || !image) return Promise.resolve();

  let appReady = false;
  let seen = false;
  let released = false;
  let returningDelayPassed = false;
  let maxTimer = 0;
  let loopTimer = 0;
  const release = (fade: boolean) => {
    if (released) return;
    released = true;
    observer.disconnect();
    window.clearTimeout(maxTimer);
    window.clearTimeout(loopTimer);
    root.removeAttribute("inert");
    root.removeAttribute("aria-hidden");
    document.documentElement.classList.remove("tilo-returning-session");
    if (fade) {
      cover.classList.add("tilo-boot-cover--leaving");
      window.setTimeout(() => cover.remove(), 300);
    } else {
      cover.remove();
    }
  };
  const reveal = () => {
    if (seen) {
      if (appReady) release(returningDelayPassed);
      return;
    }
    if (appReady) release(true);
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
  // A tiny blocking script in index.html marks returning sessions before first paint, so their cover stays hidden.
  try {
    seen = window.sessionStorage.getItem("tilo-boot-seen") === "1";
    window.sessionStorage.setItem("tilo-boot-seen", "1");
  } catch {
    // storage blocked: play the loop
  }
  maxTimer = window.setTimeout(
    () => release(!document.documentElement.classList.contains("tilo-returning-session")),
    MAX_BOOT_WAIT_MS,
  );
  if (seen) {
    window.setTimeout(() => {
      if (released) return;
      returningDelayPassed = true;
      document.documentElement.classList.remove("tilo-returning-session");
      reveal();
    }, RETURNING_DELAY_MS);
  } else {
    loopTimer = window.setTimeout(
      () => {
        cover.dataset.loopComplete = "true";
        image.src = "/loader/pool-576f781839ee.png";
        window.dispatchEvent(new Event("tilo-boot-loop-complete"));
        reveal();
      },
      reduced ? 200 : FIRST_LOOP_MS,
    );
  }
  // Resolves once the cover artwork is decoded (the cover is drawn), so the caller can load app code after it.
  // `decode()` of an animated image can stay pending (seen in embedded Chromium), which would hold the app back for
  // good: the cover waits for it at most DECODE_WAIT_MS, then app code loads anyway.
  const decoded = Promise.race([
    image.decode().catch(() => undefined),
    new Promise<void>((resolve) => window.setTimeout(resolve, DECODE_WAIT_MS)),
  ]);
  return decoded;
}
