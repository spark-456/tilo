import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const shell = readFileSync(resolve(__dirname, "AppShell.tsx"), "utf8");
const nav = readFileSync(resolve(__dirname, "TopNav.tsx"), "utf8");
const shellCss = readFileSync(resolve(__dirname, "park.shell.css"), "utf8");
const sampleCss = readFileSync(resolve(__dirname, "../sample/sample.css"), "utf8");

describe("UX_POLISH_APP_SHELL", () => {
  it("UX_POLISH_APP_SHELL shows numeric notification and Needs-you badges with clear names", () => {
    expect(shell).toContain("notificationCount=");
    expect(nav).toContain("notificationCount?: number");
    expect(nav).toContain("unread notification");
    expect(nav).toContain("aria-label={waiting");
  });

  it("UX_POLISH_APP_SHELL gives the sample banner and page controls consistent spacing and focus", () => {
    expect(sampleCss).toMatch(/\.park-first-run-banner \{[^}]*min-height: 48px/s);
    expect(shellCss).toMatch(
      /\.park-shell__main\s+:where\(a\[href\], button, input, select, textarea, summary\):focus-visible/,
    );
    expect(shellCss).toMatch(/\.park-shell__main h1 \{[^}]*text-wrap: balance/s);
  });
});
