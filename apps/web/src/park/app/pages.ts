// THROWAWAY (WEB-3b validation only): stand-in for the WEB-3a registry (placeholders only).
import { type ComponentType, type LazyExoticComponent, createElement, lazy } from "react";
import type { AppCtx, PageId } from "./AppCtx";

const LABEL: Record<PageId, string> = {
  home: "Home",
  worlds: "Worlds",
  world: "World",
  skills: "Skills",
  ledger: "Ledger",
  agenda: "Agenda",
  team: "Team",
  profile: "Profile",
  connectors: "Connectors",
};
const make = (id: PageId) =>
  lazy(() =>
    Promise.resolve({
      default: ({ app }: { app: AppCtx }) =>
        createElement(
          "section",
          { className: "park-sheet", "data-testid": `park-page-${id}` },
          createElement("h1", { tabIndex: -1 }, LABEL[id]),
          createElement("p", null, `Not built yet ${JSON.stringify(app.params)}`),
        ),
    }),
  );
export const PAGES: Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>> = {
  home: make("home"),
  worlds: make("worlds"),
  world: make("world"),
  skills: make("skills"),
  ledger: make("ledger"),
  agenda: make("agenda"),
  team: make("team"),
  profile: make("profile"),
  connectors: make("connectors"),
};
