// DEMO-BROWSER (owner screenshot, live web aeea6f78, dark theme): the Tilo browser card was a fixed light colour and its
// Hide, Pause, Stop, Earlier and Later buttons had no text colour of their own, so they took the dark theme's light
// ink and showed as empty white pills. Every surface and every button now takes the theme's role tokens (card, field,
// ink, line), with the old light values only as fallbacks for a page that has no theme.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./BrowserPanel.css", import.meta.url), "utf8");

function rule(selector: string): string {
  const at = css.indexOf(`${selector} {`);
  expect(at, `${selector} has a rule`).toBeGreaterThanOrEqual(0);
  return css.slice(at, css.indexOf("}", at));
}

describe("DEMO_BROWSER panel colours follow the theme", () => {
  it("DEMO_BROWSER the card and its text are the theme's card and ink", () => {
    const card = rule(".tilo-bv");
    expect(card).toMatch(/background: var\(--card,/);
    expect(card).toMatch(/color: var\(--ink,/);
    expect(card).toMatch(/border: 1px solid var\(--line,/);
  });

  it("DEMO_BROWSER every button sets its own text colour on a themed surface", () => {
    for (const selector of [".tilo-bv__button,\n.tilo-browser-chip"]) {
      const button = rule(selector);
      expect(button, selector).toMatch(/background: var\(--field,/);
      expect(button, selector).toMatch(/color: var\(--ink,/);
      expect(button, selector).toMatch(/border: 1px solid var\(--lineStrong,/);
    }
  });

  it("DEMO_BROWSER no surface is a fixed white that a dark theme cannot change", () => {
    const fixed = css.match(/background: (?:white|#fff\b|#ffffff\b|#f7fbff)/gi) ?? [];
    expect(fixed).toEqual([]);
  });
});
