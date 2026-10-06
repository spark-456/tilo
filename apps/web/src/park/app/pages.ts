// The page registry (plan section 10). Each page is one line: a lane replaces its line with
//   home: lazy(() => import("../pages/Home/HomePage").then((m) => ({ default: m.HomePage }))),
// (a NAMED export `HomePage` taking `{ app: AppCtx }`, no default export) and touches nothing else in this file.
import { type ComponentType, type LazyExoticComponent, lazy } from "react";
import type { AppCtx, PageId } from "./AppCtx";

const Placeholder = lazy(() => import("./Placeholder"));

export const PAGES: Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>> = {
  home: Placeholder,
  worlds: Placeholder,
  world: Placeholder,
  // biome-ignore format: the registry keeps one line per page
  skills: lazy(() => import("../pages/Skills/SkillsPage").then((m) => ({ default: m.SkillsPage }))),
  ledger: Placeholder,
  agenda: Placeholder,
  team: Placeholder,
  profile: Placeholder,
  connectors: Placeholder,
};
