// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler, stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount, q } from "../../../../test-support/park/componentsHarness";
import { settle } from "../../../../test-support/park/homeHarness";
import { ParkProvider } from "../../app/context";
import { ChatPage } from "./ChatPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const css = readFileSync(resolve(__dirname, "Chat.css"), "utf8");

describe("P0-CHAT-LAYOUT", () => {
  it("P0-CHAT-LAYOUT uses a two-pane desktop grid and one mobile pane with a contained composer", () => {
    expect(css).toMatch(/\.park-chat-grid\s*\{[^}]*box-sizing:\s*border-box/s);
    expect(css).toMatch(
      /\.park-chat-grid\s*\{[^}]*grid-template-columns:\s*272px minmax\(0,\s*1fr\)/s,
    );
    expect(css).toMatch(
      /@media \(max-width: 840px\)[\s\S]*\.park-chat-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/,
    );
    expect(css).toMatch(/\.park-chat-compose\s*\{[^}]*position:\s*sticky/s);
    expect(css).toMatch(/\.park-chat-log\s*\{[^}]*width:\s*100%/s);
    expect(css).toMatch(/\.park-chat-you\s*\{[^}]*overflow-wrap:\s*anywhere/s);
  });

  it("P0-CHAT-LAYOUT opens and closes mobile history as an accessible drawer", async () => {
    const sch = fakeScheduler();
    const m = mount(
      <ParkProvider
        api={fakeApi()}
        worldClient={null}
        navigate={vi.fn()}
        schedule={sch.schedule}
        viewport={{ vw: 390, vh: 844 }}
      >
        <ChatPage app={stubApp("chat")} />
      </ParkProvider>,
    );
    await settle();
    const toggle = q<HTMLButtonElement>(m.container, 'button[aria-label="Open chat history"]');
    const rail = q<HTMLElement>(m.container, 'aside[aria-label="Chat history drawer"]');
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(rail.getAttribute("data-open")).toBe("false");
    act(() => toggle.click());
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(rail.getAttribute("data-open")).toBe("true");
    act(() => q<HTMLButtonElement>(rail, 'button[aria-label="Close chat history"]').click());
    expect(rail.getAttribute("data-open")).toBe("false");
  });
});
