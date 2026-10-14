// The route table for every screen outside the flow shell. One row per screen: its S_NN.tsx
// component. The address pattern and the built/placeholder status live in meta.ts, so adding or
// replacing a screen is a one-line change here plus its own file.
import { type ComponentType, type ElementType, lazy } from "react";
import { CardsGallery } from "../needs-you/CardsGallery";
import { matchFlowRoute } from "../router";
import { NotFound } from "./NotFound";
import { More, ScreensIndex } from "./ScreensIndex";
import { inARun } from "./inARun";
import { SCREENS } from "./meta";

export interface ScreenProps {
  /** The pattern's capture groups, URL-decoded (world id, item id). */
  readonly params: readonly string[];
}

// Every screen is its own chunk (NFR-01): a route loads only its own code. ScreenPage holds the
// Suspense boundary, so the frame stays put while a chunk arrives.
const screen = (load: () => Promise<Record<string, unknown>>, name: string) =>
  lazy(() => load().then((m) => ({ default: m[name] as ComponentType<ScreenProps> })));
const S_09 = screen(() => import("./S_09"), "S_09");
const S_13 = screen(() => import("./S_13"), "S_13");
const S_14 = screen(() => import("./S_14"), "S_14");
const S_15 = screen(() => import("./S_15"), "S_15");
const S_16 = screen(() => import("./S_16"), "S_16");
const S_17 = screen(() => import("./S_17"), "S_17");
const S_18 = screen(() => import("./S_18"), "S_18");
const S_19 = screen(() => import("./S_19"), "S_19");
const S_21 = screen(() => import("./S_21"), "S_21");
const S_22 = screen(() => import("./S_22"), "S_22");
const S_23 = screen(() => import("./S_23"), "S_23");
const S_24 = screen(() => import("./S_24"), "S_24");
const S_26 = screen(() => import("./S_26"), "S_26");
const S_27 = screen(() => import("./S_27"), "S_27");
const S_28 = screen(() => import("./S_28"), "S_28");
const S_29 = screen(() => import("./S_29"), "S_29");
// The dev build's component gallery (WEB-2): its chunk is never reached from the landing bundle.
const DevComponents = screen(() => import("../park/dev/Components"), "Components");

// Screens that read one run from a bare address: no run yet, or an unknown world, is said, not fetched
// (a live API is never asked about the fixture world).
const Meeting = inARun(S_09, { testid: "meeting", title: "Meeting" });
const Library = inARun(S_13, { testid: "library", title: "Library" });
const Autonomy = inARun(S_15, { testid: "autonomy", title: "Autonomy" });
const Channels = inARun(S_16, { testid: "channels", title: "Channels" });
const Mail = inARun(S_17, { testid: "mail", title: "Email Autopilot" });
const Team = inARun(S_18, { testid: "team", title: "Team Lead console" });
const Connections = inARun(S_19, { testid: "connections", title: "Connections" });
const Artifacts = inARun(S_21, { testid: "artifacts", title: "Artifact history" });
const Estimate = inARun(S_23, { testid: "estimate", title: "How we estimate" });

// biome-ignore format: one line per screen keeps group edits to a single line.
const COMPONENTS: Readonly<Record<string, ElementType<ScreenProps>>> = {
  "S-09": Meeting, "S-13": Library, "S-14": S_14, "S-15": Autonomy, "S-16": Channels,
  "S-17": Mail, "S-18": Team, "S-19": Connections, "S-21": Artifacts, "S-22": S_22, "S-23": Estimate,
  "S-24": S_24, "S-26": S_26, "S-27": S_27, "S-28": S_28, "S-29": S_29,
};

export interface ScreenMatch {
  readonly id: string;
  readonly params: readonly string[];
  readonly Component: ElementType<ScreenProps>;
}

const decode = (s: string | undefined): string => {
  try {
    return decodeURIComponent(s ?? "");
  } catch {
    return s ?? ""; // a malformed escape is kept as typed, never a crash
  }
};

/** /more is the production menu; /screens is the dev-only index (PRD 18.3, AGW-08). */
const EXTRA: ReadonlyArray<{ id: string; re: RegExp; Component: ElementType<ScreenProps> }> = [
  { id: "more", re: /^\/more\/?$/, Component: More },
  ...(import.meta.env.DEV
    ? [
        { id: "screens", re: /^\/screens\/?$/, Component: ScreensIndex },
        { id: "screens-cards", re: /^\/screens\/cards\/?$/, Component: CardsGallery },
        { id: "dev-components", re: /^\/dev\/components\/?$/, Component: DevComponents },
      ]
    : []),
];

/** The screen a path belongs to, or null for the flow shell (S-01 to S-04) and unknowns. A path
 * under /world/ or /task/ that neither a screen nor a flow screen owns is "Not found", not Start. */
export function matchScreen(pathname: string): ScreenMatch | null {
  for (const { id, re, Component } of EXTRA)
    if (re.test(pathname)) return { id, params: [], Component };
  for (const { id, pattern } of SCREENS) {
    const m = pattern?.exec(pathname);
    const Component = COMPONENTS[id];
    if (m && Component) return { id, params: m.slice(1).map(decode), Component };
  }
  if (/^\/(world|task)\//.test(pathname) && matchFlowRoute(pathname).screen === "Start") {
    return { id: "not-found", params: [], Component: NotFound };
  }
  return null;
}
