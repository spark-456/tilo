// @vitest-environment happy-dom
// POLISH-2 (design review DESIGN-LIVE11, design/studio-v2): Skills on the shared page gutter, the Worlds Routines section
// with an honest empty state, the phone-docked Tilo bubble, no greyed-out live view on a sample world, and the
// Connectors category chips.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../test-support/park/appHarness";
import { parseRules } from "../../test-support/park/componentsCss";
import { cleanup, mount, q, qa } from "../../test-support/park/componentsHarness";
import {
  buttonText,
  connectedTiles,
  flush,
  makeApp,
  renderPage,
  spyApi,
  textOf,
  waitFor,
} from "../../test-support/park/connectorsDom";
import { settle } from "../../test-support/park/homeHarness";
import { mountWorld, pageText } from "../../test-support/park/worldHarness";
import { renderWorlds } from "../../test-support/park/worldsHarness";
import type { PageId } from "./app/AppCtx";
import { ParkProvider } from "./app/context";
import { chipOf } from "./pages/Connectors/view";
import { TiloBubble, dockLift, isDocked } from "./shell/TiloBubble";

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const css = (file: string) => readFileSync(join(__dirname, file), "utf8");
const decls = (sheet: string, selector: string): ReadonlyMap<string, string> =>
  new Map(
    parseRules(sheet)
      .rules.filter((r) => r.selector === selector)
      .flatMap((r) => [...r.decls]),
  );
function block(sheet: string, query: string): string {
  const at = sheet.indexOf(query);
  expect(at, query).toBeGreaterThanOrEqual(0);
  let depth = 0;
  for (let i = sheet.indexOf("{", at); i < sheet.length; i++) {
    if (sheet[i] === "{") depth++;
    if (sheet[i] === "}" && --depth === 0) return sheet.slice(sheet.indexOf("{", at) + 1, i);
  }
  throw new Error(`unclosed ${query}`);
}

describe("UI_POLISH_2 Skills gutter", () => {
  it("UI_POLISH_2 Skills uses the shell's page container, with no extra side padding on a phone", () => {
    const sheet = css("pages/Skills/SkillsStudio.css");
    const d =
      parseRules(sheet).rules.find((r) => r.selector === "[data-park] .park-skills-page")?.decls ??
      new Map<string, string>();
    expect(d.get("max-width")).toBe("var(--park-page-max, 1296px)");
    expect(d.get("padding")).toContain("var(--park-page-pad, 8px)");
    const phone = decls(block(sheet, "@media (max-width: 560px)"), "[data-park] .park-skills-page");
    expect(phone.get("padding-left")).toBe("0");
    expect(phone.get("padding-right")).toBe("0");
  });
});

describe("UI_POLISH_2 Worlds Routines", () => {
  it("UI_POLISH_2 a demo session still shows the Routines section and says there are none, with no invented rows", async () => {
    const { c } = await renderWorlds();
    const section = q(c, 'section[aria-label="Routines"]');
    expect(textOf(section)).toContain("Worlds that run on a schedule");
    expect(textOf(q(section, '[data-testid="routines-empty"]'))).toContain("No routines yet");
    expect(qa(section, "article")).toHaveLength(0);
  });
  it("UI_POLISH_2 a routine's next run is written in the routine's own timezone", async () => {
    const { RoutinesPanel } = await import("./pages/Worlds/RoutinesPanel");
    const { HttpClient } = await import("../api/http");
    const row = {
      schedule_id: "s1",
      title: "Weekly invoice check",
      cadence: { weekday: 0, hour: 9, minute: 30, tz: "Asia/Kolkata" },
      enabled: true,
      next_due: "2026-10-12T04:00:00Z",
    };
    const client = new HttpClient({
      baseUrl: "https://api.test",
      fetch: async () => new Response(JSON.stringify({ schedules: [row] })),
    });
    let m: ReturnType<typeof mount> | undefined;
    await act(async () => {
      m = mount(<RoutinesPanel client={client} />);
    });
    expect(textOf(m?.container as HTMLElement)).toContain("Next run: Mon 12 Oct, 09:30");
  });
});

describe("UI_POLISH_2 Tilo bubble on a phone", () => {
  async function mountBubble(vw: number, vh: number) {
    const m = mount(
      <ParkProvider
        api={fakeApi()}
        navigate={vi.fn()}
        schedule={fakeScheduler().schedule}
        viewport={{ vw, vh }}
      >
        <TiloBubble page={"world" as PageId} vw={vw} vh={vh} go={vi.fn()} />
      </ParkProvider>,
    );
    await settle();
    return m;
  }
  const bubble = () => q<HTMLButtonElement>(document.body, "button.park-bubble");

  it("UI_POLISH_2 dockLift clears every floating control the bubble overlaps and leaves it alone otherwise", () => {
    const box = { top: 700, bottom: 752, left: 322, right: 374 };
    expect(dockLift(box, [])).toBe(0);
    expect(dockLift(box, [{ top: 100, bottom: 200, left: 0, right: 390 }])).toBe(0);
    expect(dockLift(box, [{ top: 100, bottom: 200, left: 0, right: 100 }])).toBe(0);
    // a card across the bottom: rise until the bubble's bottom is 8px above the card's top
    expect(dockLift(box, [{ top: 690, bottom: 800, left: 16, right: 374 }])).toBe(752 - 690 + 8);
    // a second control above the first is cleared too
    const both = dockLift(box, [
      { top: 690, bottom: 800, left: 16, right: 374 },
      { top: 600, bottom: 680, left: 16, right: 374 },
    ]);
    expect(both).toBe(752 - 600 + 8);
  });

  it("UI_POLISH_2 up to 560px it is docked: not draggable, no arrow-key move, a plain label", async () => {
    expect(isDocked(560)).toBe(true);
    expect(isDocked(561)).toBe(false);
    await mountBubble(390, 844);
    const b = bubble();
    expect(b.getAttribute("data-docked")).toBe("true");
    expect(b.getAttribute("aria-label")).toBe("Your Tilo: quick answers");
    const at = { right: b.style.right, bottom: b.style.bottom };
    act(() => {
      b.dispatchEvent(
        new MouseEvent("pointerdown", { bubbles: true, clientX: 300, clientY: 700, button: 0 }),
      );
      b.dispatchEvent(
        new MouseEvent("pointermove", { bubbles: true, clientX: 100, clientY: 300, button: 0 }),
      );
      b.dispatchEvent(
        new MouseEvent("pointerup", { bubbles: true, clientX: 100, clientY: 300, button: 0 }),
      );
      b.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    });
    expect({ right: b.style.right, bottom: b.style.bottom }).toEqual(at);
  });

  it("UI_POLISH_2 it rises above an element a page marks data-park-floating, and drops back when that is gone", async () => {
    const card = document.createElement("div");
    card.setAttribute("data-park-floating", "");
    card.getBoundingClientRect = () =>
      ({ top: 690, bottom: 800, left: 16, right: 374, width: 358, height: 110 }) as DOMRect;
    document.body.append(card);
    await mountBubble(390, 844);
    const docked = Number.parseFloat(bubble().style.bottom);
    // home is {right 16, bottom 72}; the 52px bubble spans 720..772 and the card top is 690
    expect(docked).toBeGreaterThan(72);
    card.remove();
    act(() => {
      window.dispatchEvent(new Event("scroll"));
    });
    expect(Number.parseFloat(bubble().style.bottom)).toBe(72);
  });

  it("UI_POLISH_2 on a desktop it stays draggable and ignores floating controls", async () => {
    const card = document.createElement("div");
    card.setAttribute("data-park-floating", "");
    document.body.append(card);
    await mountBubble(1440, 900);
    expect(bubble().hasAttribute("data-docked")).toBe(false);
    expect(bubble().style.bottom).toBe("40px");
    card.remove();
  });

  it("UI_POLISH_2 the shell reserves room under every page on a phone through one variable", () => {
    const sheet = css("shell/park.shell.css");
    expect(
      parseRules(sheet)
        .rules.find((r) => r.selector === "[data-park]" && r.decls.has("--park-dock-space"))
        ?.decls.get("--park-dock-space"),
    ).toBe("0px");
    const phone = block(sheet, "@media (max-width: 560px)");
    expect(decls(phone, "[data-park]").get("--park-dock-space")).toMatch(/^\d+px$/);
    expect(decls(phone, "[data-park] .park-shell__page").get("padding-bottom")).toContain(
      "var(--park-dock-space",
    );
  });
});

describe("UI_POLISH_2 sample world: no greyed-out live view", () => {
  it("UI_POLISH_2 a sample world shows one chip, no Open live view and no lens links", async () => {
    const { el } = await mountWorld();
    expect(qa(el, "a.park-world-live")).toHaveLength(0);
    expect(qa(el, 'nav[aria-label="Run views"]')).toHaveLength(0);
    expect(qa(el, '[aria-disabled="true"]').filter((e) => e.tagName === "A")).toHaveLength(0);
    const chip = qa(el, ".park-world-nostage");
    expect(chip).toHaveLength(1);
    expect(textOf(chip[0] as HTMLElement)).toBe("Live view is for real runs");
    expect(pageText(el)).not.toContain("Open live view");
  });
});

describe("UI_POLISH_2 Connectors category chips", () => {
  it("UI_POLISH_2 chipOf buckets a tool's own category", () => {
    expect(chipOf("Email")).toBe("Email");
    expect(chipOf("Email and files")).toBe("Email");
    expect(chipOf("Docs")).toBe("Files");
    expect(chipOf("Calendar")).toBe("Calendar");
    expect(chipOf("Code")).toBe("Build");
    expect(chipOf("Accounting")).toBe("Other");
    expect(chipOf("")).toBe("Other");
  });

  it("UI_POLISH_2 the chips filter the list client-side and All brings everything back", async () => {
    const m = await renderPage(makeApp(), spyApi());
    await waitFor(() => connectedTiles(m.container).length > 0, "the Connected tiles");
    const group = q(m.container, ".park-connectors-chips");
    const names = qa<HTMLButtonElement>(group, "button").map(textOf);
    expect(names[0]).toBe("All");
    expect(names).toContain("Email");
    expect(names).not.toContain("Meetings"); // no tool of that category in this list: no empty chip
    const all = textOf(m.container);
    const press = async (name: string) => {
      act(() => buttonText(group, name)?.click());
      await flush(4);
    };
    await press("Calendar");
    expect(buttonText(group, "Calendar")?.getAttribute("aria-pressed")).toBe("true");
    const shown = textOf(m.container);
    expect(shown).toContain("Google Calendar");
    expect(shown).not.toContain("Slack");
    expect(shown.length).toBeLessThan(all.length);
    await press("All");
    expect(textOf(m.container)).toContain("Slack");
  });
});
