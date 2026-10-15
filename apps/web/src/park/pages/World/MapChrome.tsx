// WORLD-DESIGN (design/studio-v2 "Tilo S World.dc.html"): what sits on the city map besides the picture. The latest
// line (the artboard's "Fuel & Tolls is done" card) and the + / - zoom buttons. Nothing here moves by itself (HR-1,
// HR-2): the line is the newest recorded event's own words, and zoom is a person's click that resizes the picture.
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
import type { ActivityItem } from "../../api/types";
import { icon } from "../../shell/kit";
import { clockOf, storyOf } from "./runSteps";
import type { RunEvent } from "./useRunEvents";

export interface LatestLine {
  readonly text: string;
  readonly meta: string;
  readonly kind: "done" | "needs" | "info";
}

const DONE = /(\.completed|\.operational|artifact\.delivered)$/;
const ASKS = /(approval\.requested|help_requested|escalated|\.blocked|world\.failed)$/;

/**
 * The newest recorded line, nothing else: a real run's latest story event (its summary, as recorded, with its
 * recorded time of day), otherwise the first item of the world's own recorded activity (newest first). No line, no
 * toast: no sentence is ever made up.
 */
export function latestLine(
  events: readonly RunEvent[] | null,
  activity: readonly ActivityItem[] | undefined,
): LatestLine | null {
  const e = events ? storyOf(events)[0] : undefined;
  if (e) {
    const at = clockOf(e.ts);
    return {
      text: e.summary.trim(),
      meta: at ? `Latest recorded · ${at} UTC` : "Latest recorded",
      kind: DONE.test(e.type) ? "done" : ASKS.test(e.type) ? "needs" : "info",
    };
  }
  const a = events === null ? activity?.[0] : undefined;
  return a ? { text: a.text, meta: `${a.who} · ${a.t}`, kind: a.kind } : null;
}

const KIND_ICON = { done: "check", needs: "flag", info: "doc" } as const;

/** The artboard's top-right card: a tile with a glyph (check, flag or document: never colour alone), the line, who and when. */
export function MapToast({ line }: { line: LatestLine }) {
  return (
    <output className="park-world-toast" data-kind={line.kind} data-park-floating="">
      <span className="park-world-toast__tile" aria-hidden="true">
        {icon(KIND_ICON[line.kind], 20)}
      </span>
      <span className="park-world-toast__text">
        <span className="park-world-toast__line">{line.text}</span>
        <span className="park-world-toast__meta">{line.meta}</span>
      </span>
    </output>
  );
}

const ZOOMS = [1, 1.5, 2, 3] as const;

/**
 * The picture, sized by the chosen zoom inside a pane that scrolls once it is larger than the map (keyboard
 * reachable), with the artboard's two buttons at the bottom right. `controls` off keeps only the picture.
 */
export function ZoomableMap({ children, controls }: { children: ReactNode; controls: boolean }) {
  const [step, setStep] = useState(0);
  const pane = useRef<HTMLDivElement>(null);
  const z = controls ? (ZOOMS[step] ?? 1) : 1;
  // Zooming in keeps the middle of the city in view; zooming back out has nothing to scroll.
  useLayoutEffect(() => {
    const el = pane.current;
    if (!el || z === 1) return;
    el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
    el.scrollTop = (el.scrollHeight - el.clientHeight) / 2;
  }, [z]);
  const zoomed = z > 1;
  return (
    <>
      <div
        ref={pane}
        className={zoomed ? "park-world-pan park-world-pan--zoomed" : "park-world-pan"}
        {...(zoomed
          ? { role: "region", "aria-label": "City map, zoomed: scroll to look around", tabIndex: 0 }
          : {})}
      >
        <div className="park-world-zoomed" style={{ width: `${z * 100}%`, height: `${z * 100}%` }}>
          {children}
        </div>
      </div>
      {controls ? (
        <fieldset className="park-world-zoom" data-park-floating="">
          <legend className="park-world-sr">Map zoom</legend>
          <button
            type="button"
            className="park-world-zoom__btn"
            aria-label="Zoom in"
            aria-disabled={step >= ZOOMS.length - 1 ? "true" : undefined}
            onClick={() => setStep((s) => Math.min(s + 1, ZOOMS.length - 1))}
          >
            +
          </button>
          <button
            type="button"
            className="park-world-zoom__btn"
            aria-label="Zoom out"
            aria-disabled={step === 0 ? "true" : undefined}
            onClick={() => setStep((s) => Math.max(s - 1, 0))}
          >
            −
          </button>
          <span
            className="park-world-sr"
            aria-live="polite"
          >{`Map at ${Math.round(z * 100)}%`}</span>
        </fieldset>
      ) : null}
    </>
  );
}
