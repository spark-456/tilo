// THROWAWAY (WEB-3b validation only): stand-in for the WEB-3a router.
import { PAGE_IDS, type PageId, type Params } from "./AppCtx";

export function isParkPath(pathname: string): boolean {
  return pathname === "/park" || pathname.startsWith("/park/");
}

export function parseParkPath(
  pathname: string,
  search: string,
): { page: PageId; params: Params } | null {
  if (!isParkPath(pathname)) return null;
  const parts = pathname.split("/").filter(Boolean).slice(1);
  const seg = parts[0] ?? "home";
  if (!(PAGE_IDS as readonly string[]).includes(seg)) return null;
  const page = seg as PageId;
  const q = new URLSearchParams(search);
  if (page === "world") {
    if (parts.length !== 2 || !parts[1]) return null;
    try {
      return { page, params: { id: decodeURIComponent(parts[1]) } };
    } catch {
      return null;
    }
  }
  if (parts.length > 1) return null;
  const key = page === "skills" ? "id" : page === "team" ? "focus" : page === "profile" ? "tab" : "";
  const v = key ? q.get(key) : null;
  return { page, params: key && v ? { [key]: v } : {} };
}

export function parkPath(page: PageId, params: Params = {}): string {
  if (page === "world") return `/park/world/${encodeURIComponent(params.id ?? "")}`;
  const key = page === "skills" ? "id" : page === "team" ? "focus" : page === "profile" ? "tab" : "";
  const v = key ? params[key] : undefined;
  return `/park/${page}${key && v ? `?${key}=${encodeURIComponent(v)}` : ""}`;
}
