// README "Boot": the page bundles are fetched after the splash has gone, so the first tab click finds its page
// already loaded. Importing a module here and in app/pages.ts is the same module (one chunk, fetched once);
// a failed fetch is left for the page's own import to report. The placeholders (worlds, world) have no bundle.
const LOADERS: readonly (() => Promise<unknown>)[] = [
  () => import("../pages/Skills/SkillsPage"),
  () => import("../pages/Ledger/LedgerPage"),
  () => import("../pages/Agenda/AgendaPage"),
  () => import("../pages/Team/TeamPage"),
  () => import("../pages/Profile/ProfilePage"),
  () => import("../pages/Connectors/ConnectorsPage"),
];

export function prefetchPages(): void {
  for (const load of LOADERS) load().catch(() => undefined);
}
