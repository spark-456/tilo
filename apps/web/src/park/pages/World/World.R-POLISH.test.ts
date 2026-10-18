import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const studio = readFileSync(new URL("./World.studio.css", import.meta.url), "utf8");
const live = readFileSync(new URL("../../../worldView/live/live.css", import.meta.url), "utf8");
const chat = readFileSync(
  new URL("../../../worldView/live/ChatPopUp.tsx", import.meta.url),
  "utf8",
);

describe("R_POLISH phone World layout", () => {
  it("R_POLISH_keeps_the_stage_clear_of_the_phone_detail_panel", () => {
    expect(studio).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.park-world-panels\s*\{[^}]*position:\s*relative;[^}]*height:\s*auto;/,
    );
  });

  it("R_POLISH_gives_phone_chat_the_viewport_and_a_full_width_composer", () => {
    expect(chat).toMatch(/import\s*\{\s*createPortal\s*\}\s*from\s*["']react-dom["']/);
    expect(chat).toMatch(/phone[\s\S]*createPortal\(popup,\s*parkRoot\)/);
    expect(live).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.tw-chat-popup\s*\{[^}]*position:\s*fixed;[^}]*inset:\s*72px 8px 8px;[^}]*width:\s*auto;[^}]*height:\s*auto;/,
    );
    expect(live).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.tw-chat-bottom\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) 44px;/,
    );
    expect(live).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.tw-chat-to-badge\s*\{[^}]*grid-column:\s*1 \/ -1;/,
    );
  });
});
