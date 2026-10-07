// @vitest-environment happy-dom
// NFR-22 (PRD 17.2): a model or quota failure "offers labelled replays and a clear banner". This pins the shared
// banner both the Park app and the kept flow screens mount (BQ-NFR22-2: apps/web/src/components/ReplayBanner.tsx,
// named export `ReplayBanner`, outside park/ and screens/ so neither imports the other's tree).
//
// What it must be (PRD 18.4 error rule, UX-7, HR-1..HR-7 in PRD 9.4):
// - labelled: "Live models are unavailable" and the word "replay" are visible;
// - one action that offers a replay: a real link to the finished runs and their replays. Today that is S-14
//   "Worlds list and replays" at /worlds (screens/meta.ts), the same place NFR-24's refusal text sends people
//   ("finished runs can still be replayed"); `replaysHref` lets Park point at its own page. No sample data is made up;
// - accessible: role status or alert, the label in its accessible name, the link reachable by keyboard;
// - no motion: nothing animates without a recorded event.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ReplayBanner } from "./ReplayBanner";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const banner = () => container.querySelector<HTMLElement>('[data-testid="replay-banner"]');
const nameOf = (el: HTMLElement): string => {
  const labelled = el.getAttribute("aria-labelledby");
  if (labelled) {
    return labelled
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" ")
      .trim();
  }
  return (el.getAttribute("aria-label") ?? "").trim();
};

describe("NFR-22 ReplayBanner: a clear, labelled banner", () => {
  it("NFR_22 it renders with no props, and says live models are unavailable and that replays are offered", () => {
    act(() => root.render(<ReplayBanner />));
    const el = banner();
    expect(el, "data-testid=replay-banner").not.toBeNull();
    const text = el?.textContent ?? "";
    expect(text).toMatch(/live models are unavailable/i);
    expect(text).toMatch(/replay/i);
  });

  it("NFR_22 it says nothing new was started, and never claims to be live work or a recorded run", () => {
    act(() => root.render(<ReplayBanner />));
    const text = banner()?.textContent ?? "";
    expect(text).toMatch(/nothing new was started/i);
    expect(text).not.toMatch(/fixture|dev data|sample/i); // HR-4: it is not the fixture banner and shows no made-up data
  });

  it("NFR_22 it is role status or alert, and its accessible name carries the label", () => {
    act(() => root.render(<ReplayBanner />));
    const el = banner() as HTMLElement;
    expect(["status", "alert"]).toContain(el.getAttribute("role"));
    expect(el.getAttribute("aria-live")).not.toBe("off");
    expect(nameOf(el)).toMatch(/live models are unavailable/i);
  });

  it("NFR_22 it offers a replay as one real link to the finished runs, named with 'replay'", () => {
    act(() => root.render(<ReplayBanner />));
    const links = [...(banner()?.querySelectorAll<HTMLAnchorElement>("a[href]") ?? [])];
    expect(links).toHaveLength(1);
    const link = links[0] as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/worlds"); // S-14 Worlds list and replays
    expect((link.textContent ?? "").trim()).toMatch(/replay/i);
    expect(banner()?.querySelectorAll("button")).toHaveLength(0); // the one action is the link (UX-1)
  });

  it("NFR_22 replaysHref points the same link elsewhere (the Park app's own page)", () => {
    act(() => root.render(<ReplayBanner replaysHref="/park/worlds" />));
    const link = banner()?.querySelector<HTMLAnchorElement>("a[href]");
    expect(link?.getAttribute("href")).toBe("/park/worlds");
  });

  it("NFR_22 keyboard: the link takes focus, is not removed from the tab order, and mounting steals no focus", () => {
    const before = document.activeElement;
    act(() => root.render(<ReplayBanner />));
    expect(document.activeElement).toBe(before); // a banner never grabs focus from what the person is typing
    const link = banner()?.querySelector<HTMLAnchorElement>("a[href]") as HTMLAnchorElement;
    expect(link.tabIndex).toBeGreaterThanOrEqual(0);
    act(() => link.focus());
    expect(document.activeElement).toBe(link);
    expect(banner()?.contains(document.activeElement)).toBe(true);
  });

  it("NFR_22 it renders the same words every time (fixed copy, no props carry server text)", () => {
    act(() => root.render(<ReplayBanner />));
    const first = banner()?.textContent;
    act(() => root.render(<ReplayBanner replaysHref="/park/worlds" />));
    expect(banner()?.textContent).toBe(first);
  });
});

describe("NFR-22 ReplayBanner: no motion without a recorded event (HR-1, PRD 9.4)", () => {
  const dir = dirname(fileURLToPath(import.meta.url));
  const files = () =>
    readdirSync(dir)
      .filter((f) => /^ReplayBanner(\.[\w-]+)?\.(tsx|ts|css)$/.test(f) && !/\.test\./.test(f))
      .map((f) => join(dir, f));

  it("NFR_22 its source and styles use no animation API, transition, keyframes, timer or live-region churn", () => {
    expect(files().length).toBeGreaterThan(0);
    for (const file of files()) {
      const code = readFileSync(file, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
      expect(code, file).not.toMatch(
        /\btransition\b|\banimation\b|@keyframes|requestAnimationFrame|setInterval|setTimeout|\.animate\(|useSpring|framer/,
      );
    }
  });

  it("NFR_22 the rendered banner has no inline animation or transition style", () => {
    act(() => root.render(<ReplayBanner />));
    const html = banner()?.outerHTML ?? "";
    expect(html).not.toMatch(/animation|transition/i);
  });
});
