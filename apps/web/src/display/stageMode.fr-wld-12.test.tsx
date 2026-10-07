// @vitest-environment happy-dom
// FR-WLD-12 (PRD 9.6, 9.8, 18.2, 18.3): Stage mode (1920x1080 presenter layout, presenter hotkeys,
// reset with confirm). Stage mode is a display setting only: it hides non-stage chrome at 1920x1080,
// responds to documented presenter hotkeys outside form inputs, asks for confirmation before clearing
// demo state, and never invents or emits events (HR-1..HR-7).
import fs from "node:fs";
import path from "node:path";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";
import { forgetWorld, rememberWorld, useLastStartedWorld } from "../world/lastWorld";
import { getReplayPoint, setReplayPoint } from "../world/replayPoint";
import { useRunLog } from "../world/runLog";
import { getSelection, select } from "../world/selection";
import { getDensity, setDensity } from "./density";
import {
  PRESENTER_HOTKEYS,
  cancelResetStageDemo,
  getStageMode,
  isResetConfirmOpen,
  setStageMode,
  syncStageModeFromUrl,
} from "./stageMode";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
const originalInnerWidth = window.innerWidth;
const originalInnerHeight = window.innerHeight;

function setViewport(width: number, height: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: width });
  Object.defineProperty(window, "innerHeight", {
    configurable: true,
    writable: true,
    value: height,
  });
  window.dispatchEvent(new Event("resize"));
}

function pressKey(key: string, target: EventTarget = window, init: KeyboardEventInit = {}) {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...init,
  });
  target.dispatchEvent(event);
  return event;
}

async function mountApp(url: string, client?: FixtureClient): Promise<HTMLElement> {
  window.history.pushState({}, "", url);
  syncStageModeFromUrl();
  const activeClient = client ?? new FixtureClient();
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(
      <ClientProvider client={activeClient}>
        <App />
      </ClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 25));
  });
  return container;
}

beforeEach(() => {
  setViewport(1920, 1080);
  setDensity("friendly");
  select(FIXTURE_WORLD_ID, null);
  setReplayPoint(FIXTURE_WORLD_ID, null);
  forgetWorld();
  cancelResetStageDemo();
  window.history.pushState({}, "", `/world/${FIXTURE_WORLD_ID}/stage`);
  syncStageModeFromUrl();
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.replaceChildren();
  setViewport(originalInnerWidth, originalInnerHeight);
  setDensity("friendly");
  select(FIXTURE_WORLD_ID, null);
  setReplayPoint(FIXTURE_WORLD_ID, null);
  forgetWorld();
  cancelResetStageDemo();
  window.history.pushState({}, "", "/");
  syncStageModeFromUrl();
});

describe("FR_WLD_12 stage mode (1920x1080 layout, presenter hotkeys, reset with confirm)", () => {
  it("FR_WLD_12_stage_layout_at_1920x1080_hides_non_stage_chrome_and_keeps_stage_and_hud", async () => {
    const normal = await mountApp(`/world/${FIXTURE_WORLD_ID}/stage`);
    const shellNormal = normal.querySelector(".app-shell");
    expect(shellNormal?.getAttribute("data-stage-mode")).toBe("off");
    expect(normal.querySelector('[data-testid="top-bar"]')).not.toBeNull();
    expect(normal.querySelector('[data-testid="left-rail"]')).not.toBeNull();
    expect(normal.querySelector('[data-testid="levels-panel"]')).not.toBeNull();

    await act(async () => {
      setStageMode(true);
    });

    const shellStage = normal.querySelector(".app-shell");
    expect(shellStage?.getAttribute("data-stage-mode")).toBe("on");
    expect(shellStage?.getAttribute("data-stage-layout")).toBe("1920x1080");
    // Non-stage chrome is hidden on stage at 1920x1080:
    expect(normal.querySelector('[data-testid="top-bar"]')).toBeNull();
    expect(normal.querySelector('[data-testid="left-rail"]')).toBeNull();
    expect(normal.querySelector('[data-testid="levels-panel"]')).toBeNull();
    expect(normal.querySelector('[data-testid="assistant-open"]')).toBeNull();
    expect(normal.querySelector('[data-testid="flow-shell"]')).toBeNull();
    // Stage, HUD right rail, HR-4 banner, and presenter bar remain:
    expect(normal.querySelector('[data-testid="stage-frame"]')).not.toBeNull();
    expect(normal.querySelector('[data-testid="right-rail"]')).not.toBeNull();
    expect(normal.querySelector('[data-testid="fixture-replay-banner"]')).not.toBeNull();
    expect(normal.querySelector('[data-testid="stage-presenter"]')).not.toBeNull();
  });

  it("FR_WLD_12_presenter_hotkeys_are_documented_in_claude_md_and_control_stage_mode_density_and_replay", async () => {
    const claudeMd = fs.readFileSync(path.resolve(__dirname, "../../CLAUDE.md"), "utf8");
    for (const hk of PRESENTER_HOTKEYS) {
      expect(claudeMd).toContain(hk.key);
    }

    const client = new FixtureClient(1000);
    const container = await mountApp(`/world/${FIXTURE_WORLD_ID}/stage?speed=1000`, client);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80));
    });

    expect(getStageMode()).toBe(false);
    await act(async () => {
      pressKey("s");
    });
    expect(getStageMode()).toBe(true);
    expect(container.querySelector(".app-shell")?.getAttribute("data-stage-mode")).toBe("on");

    expect(getDensity()).toBe("friendly");
    await act(async () => {
      pressKey("d");
    });
    expect(getDensity()).toBe("professional");

    // Replay scrub hotkeys: '0' jumps to start (seq 0), ']' steps forward, '[' steps back
    await act(async () => {
      pressKey("0");
    });
    expect(getReplayPoint(FIXTURE_WORLD_ID)).toBe(0);

    await act(async () => {
      pressKey("]");
    });
    expect(getReplayPoint(FIXTURE_WORLD_ID)).toBe(EVENTS_VILLAGE_BASIC[0]?.seq ?? 1);

    await act(async () => {
      pressKey("[");
    });
    expect(getReplayPoint(FIXTURE_WORLD_ID)).toBe(0);
  });

  it("FR_WLD_12_reset_asks_for_confirmation_and_only_then_clears_demo_state", async () => {
    let remembered: string | null = null;
    function Probe() {
      remembered = useLastStartedWorld();
      return null;
    }

    const container = await mountApp(`/world/${FIXTURE_WORLD_ID}/stage?display=stage`);
    const probeRoot = createRoot(document.body.appendChild(document.createElement("div")));
    await act(async () => {
      probeRoot.render(<Probe />);
    });

    // Seed demo state
    await act(async () => {
      select(FIXTURE_WORLD_ID, "A_dir");
      setReplayPoint(FIXTURE_WORLD_ID, 12);
      rememberWorld(FIXTURE_WORLD_ID);
      setDensity("professional");
    });

    expect(getSelection(FIXTURE_WORLD_ID)).toBe("A_dir");
    expect(getReplayPoint(FIXTURE_WORLD_ID)).toBe(12);
    expect(remembered).toBe(FIXTURE_WORLD_ID);
    expect(getDensity()).toBe("professional");

    // Press 'r' presenter hotkey -> opens confirmation dialog without clearing state yet
    await act(async () => {
      pressKey("r");
    });
    expect(isResetConfirmOpen()).toBe(true);
    const dialog = container.querySelector('[data-testid="stage-reset-dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog?.textContent).toContain("Reset demo?");

    // State is still untouched before confirmation
    expect(getSelection(FIXTURE_WORLD_ID)).toBe("A_dir");
    expect(getReplayPoint(FIXTURE_WORLD_ID)).toBe(12);
    expect(remembered).toBe(FIXTURE_WORLD_ID);
    expect(getDensity()).toBe("professional");

    // Cancel via button -> closes dialog and keeps demo state intact
    const cancelBtn = container.querySelector(
      '[data-testid="stage-reset-cancel"]',
    ) as HTMLButtonElement;
    await act(async () => {
      cancelBtn.click();
    });
    expect(isResetConfirmOpen()).toBe(false);
    expect(container.querySelector('[data-testid="stage-reset-dialog"]')).toBeNull();
    expect(getSelection(FIXTURE_WORLD_ID)).toBe("A_dir");
    expect(getReplayPoint(FIXTURE_WORLD_ID)).toBe(12);

    // Open again via the Reset demo button and confirm -> clears demo state
    const openBtn = container.querySelector(
      '[data-testid="stage-reset-open"]',
    ) as HTMLButtonElement;
    await act(async () => {
      openBtn.click();
    });
    expect(container.querySelector('[data-testid="stage-reset-dialog"]')).not.toBeNull();

    const confirmBtn = container.querySelector(
      '[data-testid="stage-reset-confirm"]',
    ) as HTMLButtonElement;
    await act(async () => {
      confirmBtn.click();
    });

    expect(isResetConfirmOpen()).toBe(false);
    expect(container.querySelector('[data-testid="stage-reset-dialog"]')).toBeNull();
    expect(getSelection(FIXTURE_WORLD_ID)).toBeNull();
    expect(getReplayPoint(FIXTURE_WORLD_ID)).toBeNull();
    expect(remembered).toBeNull();
    expect(getDensity()).toBe("friendly");

    act(() => probeRoot.unmount());
  });

  it("FR_WLD_12_hotkeys_never_fire_while_typing_in_an_input_textarea_select_or_contenteditable", async () => {
    const container = await mountApp(`/world/${FIXTURE_WORLD_ID}/stage`);
    const host = document.createElement("div");
    host.innerHTML = `
      <input id="test-input" type="text" />
      <textarea id="test-textarea"></textarea>
      <select id="test-select"><option value="a">A</option></select>
      <div id="test-editable" contenteditable="true">text</div>
    `;
    container.appendChild(host);

    const targets = [
      host.querySelector("#test-input") as HTMLElement,
      host.querySelector("#test-textarea") as HTMLElement,
      host.querySelector("#test-select") as HTMLElement,
      host.querySelector("#test-editable") as HTMLElement,
    ];

    for (const el of targets) {
      el.focus();
      await act(async () => {
        for (const key of ["s", "d", "r", "[", "]", "0"]) {
          pressKey(key, el);
          pressKey(key, window);
        }
      });
      expect(getStageMode(), el.id).toBe(false);
      expect(getDensity(), el.id).toBe("friendly");
      expect(isResetConfirmOpen(), el.id).toBe(false);
      expect(getReplayPoint(FIXTURE_WORLD_ID), el.id).toBeNull();
    }
  });

  it("FR_WLD_12_honesty_stage_mode_and_reset_change_layout_only_and_never_invent_events", async () => {
    const client = new FixtureClient(1000);
    let loggedEvents: readonly unknown[] = [];
    function LogProbe() {
      loggedEvents = useRunLog(client, FIXTURE_WORLD_ID);
      return null;
    }

    const container = await mountApp(`/world/${FIXTURE_WORLD_ID}/stage?speed=1000`, client);
    const probeRoot = createRoot(document.body.appendChild(document.createElement("div")));
    await act(async () => {
      probeRoot.render(<LogProbe />);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 80));
    });

    const beforeCount = loggedEvents.length;
    expect(beforeCount).toBe(EVENTS_VILLAGE_BASIC.length);

    await act(async () => {
      pressKey("s");
      pressKey("d");
      pressKey("r");
    });
    const confirmBtn = container.querySelector(
      '[data-testid="stage-reset-confirm"]',
    ) as HTMLButtonElement;
    await act(async () => {
      confirmBtn.click();
    });

    expect(loggedEvents).toHaveLength(beforeCount);
    expect(loggedEvents).toEqual(EVENTS_VILLAGE_BASIC);

    act(() => probeRoot.unmount());
  });
});
