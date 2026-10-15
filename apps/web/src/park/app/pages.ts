import { type ComponentType, type LazyExoticComponent, lazy } from "react";
import type { AppCtx, PageId } from "./AppCtx";

export const PAGES: Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>> = {
  settings: lazy(() => import("../pages/Admin/AdminPage").then((m) => ({ default: m.AdminPage }))),
  more: lazy(() => import("../pages/Team/MorePage").then((m) => ({ default: m.MorePage }))),
  home: lazy(() => import("../pages/Home/HomePage").then((m) => ({ default: m.HomePage }))),
  // biome-ignore format: the registry keeps one line per page
  worlds: lazy(() => import("../pages/Worlds/WorldsPage").then((m) => ({ default: m.WorldsPage }))),
  // biome-ignore format: the registry keeps one line per page
  world: lazy(() => import("../pages/World/WorldPage").then((m) => ({ default: m.WorldPage }))),
  // biome-ignore format: the registry keeps one line per page
  skills: lazy(() => import("../pages/Skills/SkillsPage").then((m) => ({ default: m.SkillsPage }))),
  ledger: lazy(() => import("../pages/Ledger/LedgerPage").then((m) => ({ default: m.LedgerPage }))),
  agenda: lazy(() => import("../pages/Agenda/AgendaPage").then((m) => ({ default: m.AgendaPage }))),
  needs: lazy(() => import("../pages/Needs/NeedsPage").then((m) => ({ default: m.NeedsPage }))),
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
