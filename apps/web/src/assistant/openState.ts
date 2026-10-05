// The assistant panel's open state (FR-PA-12), shared by the launcher in the primary navigation and
// the panel. The browser session is the source of truth, so it survives a reload and a route change;
// when storage is blocked the panel simply starts closed and stays closed after a reload.
import { useSyncExternalStore } from "react";

const OPEN_KEY = "tilo.assistant.open";
const listeners = new Set<() => void>();
let fallback = false; // used only while storage is blocked, so the button still works

const readOpen = (): boolean => {
  try {
    return window.sessionStorage.getItem(OPEN_KEY) === "1";
  } catch {
    return fallback;
  }
};

export function setAssistantOpen(open: boolean): void {
  fallback = open;
  try {
    if (open) window.sessionStorage.setItem(OPEN_KEY, "1");
    else window.sessionStorage.removeItem(OPEN_KEY);
  } catch {
    // not persisted
  }
  for (const l of listeners) l();
}

export function useAssistantOpen(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    readOpen,
    () => false,
  );
}
