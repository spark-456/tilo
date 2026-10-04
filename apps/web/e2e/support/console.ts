import type { Page } from "@playwright/test";

// Console output that a browser extension injects into the page (an ad blocker's script, say) is not
// the app's, and on a developer laptop it would turn the console-error specs red (#67 item 6). It is
// recognised by where it comes from, never by what it says: an app error that merely contains the
// word "extension" or "adblock" must still be reported.
const EXTENSION_URL = /^(chrome|moz|safari-web)-extension:\/\//i;
const KNOWN_NOISE_HOST = "filtering.adblock360.com"; // the one injected script seen on the dev laptop

/** True when `url` is a script or resource of a browser extension, or of the known injected host. */
export function isHostNoiseUrl(url: string): boolean {
  if (EXTENSION_URL.test(url)) return true;
  try {
    return new URL(url).hostname === KNOWN_NOISE_HOST;
  } catch {
    return false; // not a URL (an empty source, "<anonymous>"): the app's own
  }
}

/** The script URLs named in an error's stack, line and column numbers removed. */
export function stackUrls(stack: string | undefined): string[] {
  const found = stack?.match(/\b[a-z][a-z0-9+.-]*:\/\/[^\s)]+/gi) ?? [];
  return found.map((u) => u.replace(/(:\d+){1,2}$/, ""));
}

/** An uncaught error is noise only when it has a stack and every frame is from noise: one frame of
 * the app's own makes it the app's. */
export function isHostNoiseStack(stack: string | undefined): boolean {
  const urls = stackUrls(stack);
  return urls.length > 0 && urls.every(isHostNoiseUrl);
}

/** Live list of the page's console errors, console warnings and uncaught errors, host noise left out. */
export function collectConsoleProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (m) => {
    if ((m.type() === "error" || m.type() === "warning") && !isHostNoiseUrl(m.location().url)) {
      problems.push(`[${m.type()}] ${m.text()}`);
    }
  });
  page.on("pageerror", (e) => {
    if (!isHostNoiseStack(e.stack)) problems.push(`[pageerror] ${e.message}`);
  });
  return problems;
}
