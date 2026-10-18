import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const page = readFileSync(resolve(__dirname, "ChatPage.tsx"), "utf8");
const popup = readFileSync(resolve(__dirname, "../../../worldView/live/ChatPopUp.tsx"), "utf8");

describe("UX_POLISH_CHAT", () => {
  it("UX_POLISH_CHAT gives both composers a visible Send label", () => {
    expect(page).toMatch(/<Icon name="send"[^>]*\/>\s*<span>Send<\/span>/);
    expect(popup).toMatch(/<Icon name="send"[^>]*\/>\s*<span>Send<\/span>/);
  });

  it("UX_POLISH_CHAT shows agent roles beside names in page and world bubbles", () => {
    expect(page).toContain("Personal helper");
    expect(popup).toContain("roleOf(m.from)");
    expect(popup).toContain("roleOf(turn.reply.from)");
  });
});
