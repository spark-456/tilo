// The page registry (plan section 10). Each page is one line: a lane replaces its line with
//   home: lazy(() => import("../pages/Home/HomePage").then((m) => ({ default: m.HomePage }))),
// (a NAMED export `HomePage` taking `{ app: AppCtx }`, no default export) and touches nothing else in this file.
import { type ComponentType, type LazyExoticComponent, lazy } from "react";
import type { AppCtx, PageId } from "./AppCtx";

const Placeholder = lazy(() => import("./Placeholder"));

export const PAGES: Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>> = {
  home: lazy(() => import("../pages/Home/HomePage").then((m) => ({ default: m.HomePage }))),
  worlds: Placeholder,
  world: Placeholder,
  skills: Placeholder,
  ledger: Placeholder,
  agenda: Placeholder,
  team: lazy(() => import("../pages/Team/TeamPage").then((m) => ({ default: m.TeamPage }))),
  profile: Placeholder,
  connectors: Placeholder,
};
