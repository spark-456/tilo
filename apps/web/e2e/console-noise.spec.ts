/**
 * #67 item 6 (review of #260): the console collector leaves out only output that comes from a browser
 * extension, judged by its source. An app error whose text mentions "extension" or "adblock" is
 * still reported, so the zero-console-error specs keep their teeth.
 */
import { expect, test } from "@playwright/test";
import {
  collectConsoleProblems,
  isHostNoiseStack,
  isHostNoiseUrl,
  stackUrls,
} from "./support/console";

test("#67 console noise: only extension and the known injected host count as noise, by url", () => {
  for (const url of [
    "chrome-extension://abcdef/inject.js",
    "moz-extension://1234/content.js",
    "https://filtering.adblock360.com/script.js",
  ]) {
    expect(isHostNoiseUrl(url), url).toBe(true);
  }
  for (const url of [
    "",
    "<anonymous>",
    "http://127.0.0.1:5392/src/main.tsx",
    "https://filtering.adblock360.com.evil.test/x.js",
    "https://example.test/chrome-extension://x.js",
  ]) {
    expect(isHostNoiseUrl(url), url).toBe(false);
  }
});

test("#67 console noise: an uncaught error is noise only when every frame is", () => {
  const ext = "    at inject (chrome-extension://abcdef/inject.js:1:2)";
  const app = "    at boot (http://127.0.0.1:5392/src/main.tsx:10:4)";
  expect(stackUrls(`Error: x\n${ext}`)).toEqual(["chrome-extension://abcdef/inject.js"]);
  expect(isHostNoiseStack(`Error: x\n${ext}`)).toBe(true);
  expect(isHostNoiseStack(`Error: x\n${ext}\n${app}`)).toBe(false);
  expect(isHostNoiseStack("Error: x")).toBe(false); // no stack: reported
  expect(isHostNoiseStack(undefined)).toBe(false);
});

test("#67 console noise: app errors that mention extension or adblock are still reported", async ({
  page,
}) => {
  const problems = collectConsoleProblems(page);
  await page.setContent("<!doctype html><title>t</title>");
  await page.evaluate(() => {
    console.error("Failed to parse fixture: unsupported file extension .jsonl");
    console.warn("AdBlock-style class name crash in the app");
    setTimeout(() => {
      throw new Error("Unhandled: extension point undefined");
    });
  });
  await expect.poll(() => problems.length).toBe(3);
  expect(problems.join("\n")).toContain("unsupported file extension .jsonl");
  expect(problems.join("\n")).toContain("AdBlock-style class name crash");
  expect(problems.join("\n")).toContain("extension point undefined");
});

test("#67 console noise: output from an extension script is dropped, the app's own beside it is not", async ({
  page,
}) => {
  const problems = collectConsoleProblems(page);
  await page.setContent("<!doctype html><title>t</title>");
  // A script whose source URL is an extension's, as an injected content script has.
  await page.evaluate(
    "console.error('from an extension');\n//# sourceURL=chrome-extension://abcdef/inject.js",
  );
  await page.evaluate(() => console.error("from the app"));
  await expect.poll(() => problems.length).toBeGreaterThan(0);
  expect(problems).toEqual(["[error] from the app"]);
});
