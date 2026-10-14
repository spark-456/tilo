// Replace old bookmarks while keeping only the selected run.
// OLD-UI-OUT wave 1: the old Start, Understanding and Approaches screens are gone (Park Home starts a run in one
// step): a stale link to one of their addresses goes to Home.
const RETIRED_FLOW = /^\/(?:start|task\/[^/]+\/(?:understanding|approaches))\/?$/;
const TARGETS: Record<string, string> = {
  autonomy: "/settings?section=autonomy",
  channels: "/settings?section=channels",
  estimate: "/settings?section=estimate",
  pilot: "/settings?section=pilot",
  mail: "/team?focus=mail",
  "team/console": "/team?focus=console",
  connections: "/connectors",
};
export function adminRedirect(path: string, search = ""): string | null {
  if (RETIRED_FLOW.test(path)) return "/";
  const target = TARGETS[path.replace(/^\//, "").replace(/\/$/, "")];
  if (!target) return null;
  const url = new URL(target, "https://tilo.invalid");
  const world = new URLSearchParams(search).get("world");
  if (world) url.searchParams.set("world", world);
  return url.pathname + url.search;
}
