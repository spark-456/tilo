// The page registry (plan section 10). Each page is one line: a lane replaces its line with
//   home: lazy(() => import("../pages/Home")),
// (a default export taking `{ app: AppCtx }`) and touches nothing else in this file.
import { type ComponentType, type LazyExoticComponent, lazy } from "react";
import type { AppCtx, PageId } from "./AppCtx";

const Placeholder = lazy(() => import("./Placeholder"));

export const PAGES: Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>> = {
  home: Placeholder,
  worlds: Placeholder,
  world: Placeholder,
  skills: Placeholder,
  ledger: Placeholder,
  agenda: Placeholder,
  team: lazy(() => import("../pages/Team/TeamPage").then((m) => ({ default: m.TeamPage }))),
  profile: Placeholder,
  connectors: Placeholder,
};
