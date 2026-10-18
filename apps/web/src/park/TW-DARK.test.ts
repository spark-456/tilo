// TW-DARK: Make the World page, the chat pop-up and the Result tab good in dark mode:
// fix contrast and unreadable text to WCAG AA.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const WORLD_CSS_PATH = resolve(__dirname, "pages/World/World.css");
const WORLD_STUDIO_CSS_PATH = resolve(__dirname, "pages/World/World.studio.css");
const BUBBLE_CSS_PATH = resolve(__dirname, "shell/TiloBubble.css");
const LIVE_CSS_PATH = resolve(__dirname, "../worldView/live/live.css");

const worldCss = `${readFileSync(WORLD_CSS_PATH, "utf8")}\n${readFileSync(WORLD_STUDIO_CSS_PATH, "utf8")}`;
const bubbleCss = readFileSync(BUBBLE_CSS_PATH, "utf8");
const liveCss = readFileSync(LIVE_CSS_PATH, "utf8");

/** Calculate relative luminance according to WCAG 2.1 specifications */
function relativeLuminance(r: number, g: number, b: number): number {
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * (rs ?? 0) + 0.7152 * (gs ?? 0) + 0.0722 * (bs ?? 0);
}

/** Calculate contrast ratio between two hex colors according to WCAG 2.1 specifications */
function contrastRatio(hex1: string, hex2: string): number {
  const parseHex = (h: string) => {
    const clean = h.replace("#", "");
    const full =
      clean.length === 3
        ? clean
            .split("")
            .map((c) => c + c)
            .join("")
        : clean;
    const num = Number.parseInt(full, 16);
    return [(num >> 16) & 255, (num >> 8) & 255, num & 255] as const;
  };
  const [r1, g1, b1] = parseHex(hex1);
  const [r2, g2, b2] = parseHex(hex2);
  const l1 = relativeLuminance(r1, g1, b1);
  const l2 = relativeLuminance(r2, g2, b2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

describe("TW-DARK: Contrast calculations verifying WCAG AA requirements", () => {
  it("verifies why --hero (#7A62F5) under white fails WCAG AA but --heroFill (#6C52EB) passes", () => {
    const heroRatio = contrastRatio("#FFFFFF", "#7A62F5");
    const heroFillRatio = contrastRatio("#FFFFFF", "#6C52EB");
    expect(heroRatio).toBeLessThan(4.5); // 4.29:1 fails WCAG AA
    expect(heroFillRatio).toBeGreaterThanOrEqual(4.5); // 5.19:1 passes WCAG AA
  });

  it("verifies why white on --ok (#5CCB86) fails WCAG AA and dark text (#1F1D2B) passes", () => {
    const whiteOnGreenRatio = contrastRatio("#FFFFFF", "#5CCB86");
    const darkOnGreenRatio = contrastRatio("#1F1D2B", "#5CCB86");
    expect(whiteOnGreenRatio).toBeLessThan(4.5); // ~2.0:1 fails WCAG AA
    expect(darkOnGreenRatio).toBeGreaterThanOrEqual(4.5); // ~8.4:1 passes WCAG AA
  });

  it("verifies ink text (#F4F2FA) contrast on night dark surfaces", () => {
    const onPaper = contrastRatio("#F4F2FA", "#14163A");
    const onPop = contrastRatio("#F4F2FA", "#23264F");
    expect(onPaper).toBeGreaterThanOrEqual(7.0); // WCAG AAA
    expect(onPop).toBeGreaterThanOrEqual(7.0); // WCAG AAA
  });

  it("verifies code text amber (#F7C85C) and link heroInk (#BCAFFF) contrast on night surfaces", () => {
    const amberOnPaper = contrastRatio("#F7C85C", "#14163A");
    const linkOnPaper = contrastRatio("#BCAFFF", "#14163A");
    expect(amberOnPaper).toBeGreaterThanOrEqual(4.5);
    expect(linkOnPaper).toBeGreaterThanOrEqual(4.5);
  });
});

describe("TW-DARK: World page dark mode WCAG AA rules in World.css", () => {
  it("has night-mode styling for the Slack and Result dialog modals", () => {
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-world-slackdialog[\s\S]*?background:\s*var\(--pop/,
    );
  });

  it("has night-mode styling for .park-world-resulttext and .park-world-out", () => {
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-world-resulttext[\s\S]*?background:/,
    );
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-world-out[\s\S]*?color:\s*var\(--ink/,
    );
  });

  it("has night-mode styling for result code blocks and pre", () => {
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-world-resulttext\s+pre/,
    );
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-world-resulttext\s+code/,
    );
  });

  it("fixes completed step marks to have dark text in night mode for WCAG AA", () => {
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-world-step--done\s+\.park-world-stepmark[\s\S]*?color:\s*var\(--inv/,
    );
  });

  it("uses --heroFill for lovablelink in night mode for WCAG AA contrast", () => {
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-world-lovablelink[\s\S]*?background:\s*var\(--heroFill/,
    );
  });

  it("provides night-mode focus outlines with contrast compliant colors", () => {
    expect(worldCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*:focus-visible[\s\S]*?outline-color:\s*var\(--(?:heroInk|focus|ink)/,
    );
  });
});

describe("TW-DARK: Chat pop-up dark mode WCAG AA rules in TiloBubble.css", () => {
  it("has night-mode opaque background for the compact chat panel", () => {
    expect(bubbleCss).toMatch(
      /\[data-park\]\[data-time="night"\]\s+\.park-bubble__panel[\s\S]*?background:\s*var\(--pop/,
    );
  });

  it("has night-mode styling for the Tilo incoming message bubble", () => {
    expect(bubbleCss).toMatch(
      /\[data-park\]\[data-time="night"\]\s+\.park-bubble__tilo[\s\S]*?color:\s*var\(--ink/,
    );
  });

  it("uses --heroFill for the user outgoing message bubble in night mode for WCAG AA contrast", () => {
    expect(bubbleCss).toMatch(
      /\[data-park\]\[data-time="night"\]\s+\.park-bubble__you[\s\S]*?background:\s*var\(--heroFill/,
    );
  });

  it("has night-mode styling for the chat quick buttons and input", () => {
    expect(bubbleCss).toMatch(/\[data-park\]\[data-time="night"\]\s+\.park-bubble__go\s+button/);
    expect(bubbleCss).toMatch(
      /\[data-park\]\[data-time="night"\][^{]*\.park-bubble__input::placeholder/,
    );
  });
});

describe("TW-DARK: Live Chat pop-up dark mode WCAG AA rules in live.css", () => {
  it("has night-mode opaque background and border for the live chat pop-up", () => {
    expect(liveCss).toMatch(
      /\[data-park\]\[data-time="night"\]\s+\.tw-chat-popup[\s\S]*?background:\s*var\(--pop/,
    );
  });

  it("has night-mode styling for incoming and outgoing chat bubbles", () => {
    expect(liveCss).toMatch(
      /\[data-park\]\[data-time="night"\]\s+\.tw-chat-bubble[\s\S]*?color:\s*var\(--ink/,
    );
    expect(liveCss).toMatch(
      /\[data-park\]\[data-time="night"\]\s+\.tw-chat-bubble--me[\s\S]*?background:\s*var\(--heroFill/,
    );
  });

  it("has night-mode styling for filters and input", () => {
    expect(liveCss).toMatch(
      /\[data-park\]\[data-time="night"\]\s+\.tw-chat-filter--active[\s\S]*?background:\s*var\(--heroFill/,
    );
    expect(liveCss).toMatch(/\[data-park\]\[data-time="night"\]\s+\.tw-chat-input/);
  });
});
