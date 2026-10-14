// OLD-UI-OUT-4: replace old bookmarks, retaining the selected run without adding a history entry.
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
  const target = TARGETS[path.replace(/^\//, "").replace(/\/$/, "")];
  if (!target) return null;
  const url = new URL(target, "https://tilo.invalid");
  const world = new URLSearchParams(search).get("world");
  if (world) url.searchParams.set("world", world);
  return url.pathname + url.search;
}
