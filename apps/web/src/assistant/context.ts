// The context chip (FR-PA-12): which screen the person is on and, on a world, which record is
// selected, read from the address and the display selection only. Never from the DOM.
import { matchFlowRoute } from "../router";
import { SCREENS } from "../screens/meta";
import { matchScreen } from "../screens/routes";
import type { AssistantContext } from "./adapter";

/** "Library and Memory Vault" -> "Library": the PRD's screen name up to its first "and" or "with". */
const short = (name: string): string => name.split(/ and | with /)[0] ?? name;

export function contextOf(pathname: string, record: string | null): AssistantContext {
  const screen = matchScreen(pathname);
  const label = screen
    ? screen.id === "not-found"
      ? "Not found"
      : short(SCREENS.find((s) => s.id === screen.id)?.name ?? screen.id)
    : matchFlowRoute(pathname).screen;
  return { label, route: pathname, record };
}

/** The world a path belongs to, for reading its selection (null off a world). */
export function worldOf(pathname: string): string | null {
  const m = /^\/world\/([^/]+)/.exec(pathname);
  if (!m?.[1]) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}
