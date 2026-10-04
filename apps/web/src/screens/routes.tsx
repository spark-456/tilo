// The route table for every screen outside the flow shell. One row per screen: its S_NN.tsx
// component. The address pattern and the built/placeholder status live in meta.ts, so adding or
// replacing a screen is a one-line change here plus its own file.
import type { ComponentType } from "react";
import { CardsGallery } from "../needs-you/CardsGallery";
import { matchFlowRoute } from "../router";
import { NotFound } from "./NotFound";
import { S_05 } from "./S_05";
import { S_06 } from "./S_06";
import { S_07 } from "./S_07";
import { S_08 } from "./S_08";
import { S_09 } from "./S_09";
import { S_10 } from "./S_10";
import { S_11 } from "./S_11";
import { S_12 } from "./S_12";
import { S_13 } from "./S_13";
import { S_14 } from "./S_14";
import { S_15 } from "./S_15";
import { S_16 } from "./S_16";
import { S_17 } from "./S_17";
import { S_18 } from "./S_18";
import { S_19 } from "./S_19";
import { S_21 } from "./S_21";
import { S_22 } from "./S_22";
import { S_23 } from "./S_23";
import { S_24 } from "./S_24";
import { More, ScreensIndex } from "./ScreensIndex";
import { inARun } from "./inARun";
import { SCREENS } from "./meta";

export interface ScreenProps {
  /** The pattern's capture groups, URL-decoded (world id, item id). */
  readonly params: readonly string[];
}

// Screens that read one run from a bare address: no run yet, or an unknown world, is said, not fetched.
const NeedsYou = inARun(S_06, { testid: "needs-you", title: "Needs you" });
const GateSheet = inARun(S_07, { testid: "gate-sheet-page", title: "Approval gate" });
const Library = inARun(S_13, { testid: "library", title: "Library" });

// biome-ignore format: one line per screen keeps group edits to a single line.
const COMPONENTS: Readonly<Record<string, ComponentType<ScreenProps>>> = {
  "S-05": S_05, "S-06": NeedsYou, "S-07": GateSheet, "S-08": S_08, "S-09": S_09, "S-10": S_10,
  "S-11": S_11, "S-12": S_12, "S-13": Library, "S-14": S_14, "S-15": S_15, "S-16": S_16, "S-17": S_17,
  "S-18": S_18, "S-19": S_19, "S-21": S_21, "S-22": S_22, "S-23": S_23, "S-24": S_24,
};

export interface ScreenMatch {
  readonly id: string;
  readonly params: readonly string[];
  readonly Component: ComponentType<ScreenProps>;
}

const decode = (s: string | undefined): string => {
  try {
    return decodeURIComponent(s ?? "");
  } catch {
    return s ?? ""; // a malformed escape is kept as typed, never a crash
  }
};

/** /more is the production menu; /screens is the dev-only index (PRD 18.3, AGW-08). */
const EXTRA: ReadonlyArray<{ id: string; re: RegExp; Component: ComponentType<ScreenProps> }> = [
  { id: "more", re: /^\/more\/?$/, Component: More },
  ...(import.meta.env.DEV
    ? [
        { id: "screens", re: /^\/screens\/?$/, Component: ScreensIndex },
        { id: "screens-cards", re: /^\/screens\/cards\/?$/, Component: CardsGallery },
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
