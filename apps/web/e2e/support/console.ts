import type { Page } from "@playwright/test";

// Console output a browser extension injects into the page (an ad blocker's script, say); it is not
// the app's, and on a developer laptop it would turn the console-error specs red (#67 item 6).
const HOST_NOISE = /adblock|extension/i;

/** Live list of the page's console errors, console warnings and uncaught errors, host noise left out. */
export function collectConsoleProblems(page: Page): string[] {
  const problems: string[] = [];
  const add = (line: string) => {
    if (!HOST_NOISE.test(line)) problems.push(line);
  };
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") add(`[${m.type()}] ${m.text()}`);
  });
  page.on("pageerror", (e) => add(`[pageerror] ${e.message}`));
  return problems;
}
