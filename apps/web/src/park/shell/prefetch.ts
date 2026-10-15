import type { PageId } from "../app/AppCtx";

// X-PERF-1: prefetch only the tab the person points to or focuses. The route uses
// the same import; a failed speculative request is left for its boundary to report.
const LOADERS: Partial<Record<PageId, () => Promise<unknown>>> = {
  worlds: () => import("../pages/Worlds/WorldsPage"),
  skills: () => import("../pages/Skills/SkillsPage"),
  needs: () => import("../pages/Needs/NeedsPage"),
  ledger: () => import("../pages/Ledger/LedgerPage"),
  agenda: () => import("../pages/Agenda/AgendaPage"),
  team: () => import("../pages/Team/TeamPage"),
};

export function prefetchPage(page: PageId): void {
  void LOADERS[page]?.().catch(() => undefined);
}
