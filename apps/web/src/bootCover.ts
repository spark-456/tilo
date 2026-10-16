/** The HTML cover exists before the JavaScript bundle. Release it after the app and one saved loop are ready. */
export function installBootCover(): void {
  const cover = document.getElementById("tilo-boot-cover");
  const root = document.getElementById("root");
  const image = cover?.querySelector("img");
  if (!cover || !root || !image) return;

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
  void image
    .decode()
    .catch(() => undefined)
    .then(() => {
      window.setTimeout(
        () => {
          loopReady = true;
          reveal();
        },
        reduced ? 200 : 4600,
      );
    });
}
