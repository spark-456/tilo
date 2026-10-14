// FR-WLD-12 (PRD 9.6, 9.8, 18.2, 18.3): Stage mode display setting, presenter hotkeys and reset
// with confirmation. Stage mode is a display setting only: it changes layout and UI scale, never
// invents or emits events (HR-1..HR-7).
import type { Event } from "@tilo/contracts";
import { useSyncExternalStore } from "react";
import { forgetWorld } from "../world/lastWorld";
import {
  clearReplayPoints,
  getReplayPoint,
  indexToPoint,
  pointToIndex,
  setReplayPoint,
} from "../world/replayPoint";
import { clearSelections, select } from "../world/selection";
import { getDensity, setDensity } from "./density";

export interface PresenterHotkey {
  readonly key: string;
  readonly label: string;
  readonly action: string;
}

/** Documented presenter hotkeys (listed in apps/web/CLAUDE.md). */
export const PRESENTER_HOTKEYS: readonly PresenterHotkey[] = [
  { key: "s", label: "s", action: "Toggle stage mode (1920x1080 presenter layout)" },
  { key: "d", label: "d", action: "Toggle display density (Friendly / Professional)" },
  { key: "r", label: "r", action: "Reset demo state (opens confirmation dialog)" },
  { key: "[", label: "[", action: "Step replay backward one event" },
  { key: "]", label: "]", action: "Step replay forward one event" },
  { key: "0", label: "0", action: "Jump replay to start (seq 0)" },
  { key: "Escape", label: "Escape", action: "Cancel reset dialog or clear selection" },
];

const listeners = new Set<() => void>();
let override: boolean | null = null;
let confirmOpen = false;

function readUrlStageMode(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("display") === "stage";
}

function applyDataset(on: boolean): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.stageMode = on ? "on" : "off";
}

function notify(): void {
  for (const l of [...listeners]) l();
}

export function getStageMode(): boolean {
  return override ?? readUrlStageMode();
}

export function setStageMode(next: boolean): void {
  override = next;
  applyDataset(next);
  notify();
}

export function toggleStageMode(): boolean {
  const next = !getStageMode();
  setStageMode(next);
  return next;
}

/** Resets manual override so stage mode reflects `?display=stage` in `window.location.search`. */
export function syncStageModeFromUrl(): void {
  override = null;
  applyDataset(getStageMode());
  notify();
}

export function subscribeStageMode(onChange: () => void): () => void {
  listeners.add(onChange);
  const onPopState = () => {
    override = null;
    applyDataset(getStageMode());
    onChange();
  };
  if (typeof window !== "undefined") {
    window.addEventListener("popstate", onPopState);
  }
  return () => {
    listeners.delete(onChange);
    if (typeof window !== "undefined") {
      window.removeEventListener("popstate", onPopState);
    }
  };
}

export const useStageMode = (): readonly [boolean, (next: boolean) => void, () => boolean] => [
  useSyncExternalStore(subscribeStageMode, getStageMode),
  setStageMode,
  toggleStageMode,
];

export const isResetConfirmOpen = (): boolean => confirmOpen;

export function askResetStageDemo(): void {
  if (confirmOpen) return;
  confirmOpen = true;
  notify();
}

export function cancelResetStageDemo(): void {
  if (!confirmOpen) return;
  confirmOpen = false;
  notify();
}

/** Clears demo display state only after explicit confirmation. Never emits or modifies events. */
export function confirmResetStageDemo(worldId?: string | null): void {
  confirmOpen = false;
  clearSelections();
  if (worldId) select(worldId, null);
  clearReplayPoints();
  if (worldId) setReplayPoint(worldId, null);
  forgetWorld();
  setDensity("friendly");
  notify();
}

export const useResetConfirm = (): boolean =>
  useSyncExternalStore(subscribeStageMode, isResetConfirmOpen);

function isEditableElement(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName.toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if ((el as HTMLElement).isContentEditable) return true;
  const attr = el.getAttribute("contenteditable");
  if (attr !== null && attr.toLowerCase() !== "false") return true;
  return (
    el.closest("input, textarea, select, [contenteditable]:not([contenteditable='false'])") !== null
  );
}

/** True when a keyboard event originates from or occurs while focused in a form or editable input. */
export function isEditableTarget(target: EventTarget | null): boolean {
  const targetEl = target instanceof Element ? target : null;
  if (isEditableElement(targetEl)) return true;
  const activeEl = typeof document !== "undefined" ? document.activeElement : null;
  return isEditableElement(activeEl);
}

/** Handles presenter hotkeys when not typing in an input. Returns true when a hotkey was handled. */
export function handlePresenterHotkey(
  e: KeyboardEvent,
  context: {
    readonly worldId: string | null;
    readonly events: readonly Event[];
    readonly finished: boolean;
  },
): boolean {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return false;
  if (isEditableTarget(e.target)) return false;

  const key = e.key;
  if (key === "Escape") {
    if (confirmOpen) {
      e.preventDefault();
      cancelResetStageDemo();
      return true;
    }
    if (context.worldId) {
      select(context.worldId, null);
      return true;
    }
    return false;
  }

  if (key === "s" || key === "S") {
    e.preventDefault();
    toggleStageMode();
    return true;
  }

  if (key === "d" || key === "D") {
    e.preventDefault();
    setDensity(getDensity() === "friendly" ? "professional" : "friendly");
    return true;
  }

  if (key === "r" || key === "R") {
    e.preventDefault();
    askResetStageDemo();
    return true;
  }

  if (context.worldId && context.finished && context.events.length > 0) {
    const currentIndex = pointToIndex(context.events, getReplayPoint(context.worldId));
    if (key === "0") {
      e.preventDefault();
      setReplayPoint(context.worldId, 0);
      return true;
    }
    if (key === "[") {
      e.preventDefault();
      const prev = Math.max(0, currentIndex - 1);
      setReplayPoint(context.worldId, indexToPoint(context.events, prev));
      return true;
    }
    if (key === "]") {
      e.preventDefault();
      const next = Math.min(context.events.length, currentIndex + 1);
      setReplayPoint(context.worldId, indexToPoint(context.events, next));
      return true;
    }
  }

  return false;
}
