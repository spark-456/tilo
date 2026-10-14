// The page registry (plan section 10). Each page is one line: a lane replaces its line with
//   home: lazy(() => import("../pages/Home/HomePage").then((m) => ({ default: m.HomePage }))),
// (a NAMED export `HomePage` taking `{ app: AppCtx }`, no default export) and touches nothing else in this file.
import { type ComponentType, type LazyExoticComponent, lazy } from "react";
import type { AppCtx, PageId } from "./AppCtx";

const Placeholder = lazy(() => import("./Placeholder"));

export const PAGES: Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>> = {
  home: lazy(() => import("../pages/Home/HomePage").then((m) => ({ default: m.HomePage }))),
  // biome-ignore format: the registry keeps one line per page
  worlds: lazy(() => import("../pages/Worlds/WorldsPage").then((m) => ({ default: m.WorldsPage }))),
  // biome-ignore format: the registry keeps one line per page
  world: lazy(() => import("../pages/World/WorldPage").then((m) => ({ default: m.WorldPage }))),
  // biome-ignore format: the registry keeps one line per page
  skills: lazy(() => import("../pages/Skills/SkillsPage").then((m) => ({ default: m.SkillsPage }))),
  ledger: lazy(() => import("../pages/Ledger/LedgerPage").then((m) => ({ default: m.LedgerPage }))),
  agenda: lazy(() => import("../pages/Agenda/AgendaPage").then((m) => ({ default: m.AgendaPage }))),
  team: lazy(() => import("../pages/Team/TeamPage").then((m) => ({ default: m.TeamPage }))),
  profile: lazy(() =>
    import("../pages/Profile/ProfilePage").then((m) => ({ default: m.ProfilePage })),
  ),
  connectors: lazy(() =>
    import("../pages/Connectors/ConnectorsPage").then((m) => ({ default: m.ConnectorsPage })),
  ),
  library: lazy(() =>
    import("../pages/Library/LibraryPage").then((m) => ({ default: m.LibraryPage })),
  ),
};
