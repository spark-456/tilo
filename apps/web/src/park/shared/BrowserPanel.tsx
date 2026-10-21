// DEMO-BROWSER: Tilo's browser as the person sees it. Every picture, caption and cursor comes from a recorded
// browser.started / browser.acted / browser.stopped event (HR-1, BR-09: only frames named by recorded events, in order,
// no video, nothing in between); which picture is shown, enlarging it, going back to the map and where the window sits
// are display state only. On the World page it takes over the map area while the run has a browser session
// ("takeover", and a floating window once the person drags it); on its own page it fills the page ("page", the address
// "Open in new tab" opens); elsewhere it is a card in the page ("inline").
import type { BrowserActedData, BrowserStartedData, BrowserStoppedData } from "@tilo/contracts";
import {
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type { TiloClient } from "../../api/client";
import { browserPath } from "../app/router";
import "./BrowserPanel.css";

type FrameClient = TiloClient & {
  getBrowserFrame?: (worldId: string, artifactId: string) => Promise<Blob>;
  stopBrowser?: (worldId: string, session: string) => Promise<void>;
};

type Cursor = { seq: number; x: number; y: number; caption: string };

/** The floating window's top-left corner, in window px. */
type FloatPos = { left: number; top: number };
type Size = { w: number; h: number };
const POS_KEY = "tilo.browser.pos";
const FLOAT_WIDTH = 720;
const EDGE = 8;
const NAV_CLEAR = 84;
const STEP = 16;
const DRAG_FROM = 4;
/** Narrower than this (phone width) the view is full width in the map area: no drag, no Dock. */
const DRAG_MIN_WIDTH = 761;

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

function readPos(): FloatPos | null {
  try {
    const saved: unknown = JSON.parse(window.localStorage.getItem(POS_KEY) ?? "null");
    const { left, top } = (saved ?? {}) as { left?: unknown; top?: unknown };
    return isNum(left) && isNum(top) ? { left, top } : null;
  } catch {
    return null;
  }
}
function writePos(pos: FloatPos | null): void {
  try {
    if (pos === null) window.localStorage.removeItem(POS_KEY);
    else window.localStorage.setItem(POS_KEY, JSON.stringify(pos));
  } catch {
    // storage blocked: the place lasts this visit only
  }
}

/** Keeps the whole window on screen: EDGE from the sides and the bottom, and below the page's fixed nav (it ends at
 * 76px) so the window's bar can always be reached. */
function clampPos(p: FloatPos, win: Size, box: Size): FloatPos {
  const fit = (n: number, min: number, room: number) =>
    Math.round(Math.min(Math.max(n, min), Math.max(min, room)));
  return {
    left: fit(p.left, EDGE, win.w - box.w - EDGE),
    top: fit(p.top, NAV_CLEAR, win.h - box.h - EDGE),
  };
}

function useWindowSize(): Size {
  const [size, setSize] = useState(() => ({ w: window.innerWidth, h: window.innerHeight }));
  useEffect(() => {
    const on = () =>
      setSize((s) =>
        s.w === window.innerWidth && s.h === window.innerHeight
          ? s
          : { w: window.innerWidth, h: window.innerHeight },
      );
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);
  return size;
}

/** The server would not serve a recorded frame (not screened clean, or missing): said once, never a spinner. */
export const FRAME_UNAVAILABLE =
  "This picture is hidden because Tilo's safety check could not clear it, but the steps still show what the browser did.";

/** DEMO-BROWSER: why the browser stopped (`browser.stopped` outcome), each one plain sentence with what to try. */
export const STOP_LINES = {
  done: "Finished.",
  stopped: "You stopped the browser.",
  taken_over: "You took over the browser.",
  needs_person: "This step needs you, so open the site yourself to finish it.",
  login_wall:
    "This site wants a sign-in, which Tilo never does, so try a page that is open to everyone.",
  cap_steps: "The browser used all its steps, so ask for one smaller thing at a time.",
  cap_credits: "The browser used its credit limit, so ask for one smaller thing at a time.",
  session_lost: "The browser stopped early, so try the task again.",
  error: "The browser stopped early, so try the task again.",
} as const;

/** A refused browser action (`browser.acted` reason), said instead of the stop line when it is the cause. */
export const REFUSAL_LINES = {
  offsite_host: "Tilo only opens the sites you named, so add that site to your task.",
  secure_field: "Tilo never types passwords or codes, so sign in yourself if the site needs it.",
  secret_text: "Tilo never types passwords or codes, so sign in yourself if the site needs it.",
  download: "Tilo does not download files, so open the site yourself to get the file.",
  login_wall: STOP_LINES.login_wall,
  target_changed: "The page changed while Tilo looked at it, so try the task again.",
} as const;

/** DEMO-BROWSER (live 21 Oct): while a session is open between steps, Tilo is deciding the next one; when the run
 * records that the browser's model is busy (tilo-api `BROWSER_BUSY_LINE`, an agent.working line), the panel says so. */
export const DECIDING_LINE = "Tilo is deciding the next step…";
export const BUSY_LINE = "The model is busy, so Tilo's browser is trying again.";

/** A commit the browser stopped before (BR-05). */
export const GATED_LINE =
  "Tilo stopped before submitting anything, so open the site yourself to finish this step.";

/** The finished state: how many recorded steps there are to replay. */
export const finishedLine = (steps: number) =>
  `Finished: ${steps} ${steps === 1 ? "step" : "steps"}; pick any step to see it again.`;

const lineOf = (lines: Readonly<Record<string, string>>, key: string | null): string | undefined =>
  key ? lines[key] : undefined;

/** One recorded step: its own frame (the page after the step), its caption, where Tilo's mouse was, and, for a step that
 * changes the page, the frame before it. */
type Frame = {
  artifactId: string;
  caption: string;
  cursor: Cursor | null;
  host: string | null;
  before: string | null;
};

/** One picture the panel can show; `phase` says which side of a click, typed field or key press it is. */
type Picture = { step: number; artifactId: string; phase: "before" | "after" | null };

type BrowserEvent = { seq: number; type: string; data?: unknown; summary?: string };

/** Actions that have a real mouse or focus point (the event's target box); extract and navigate have none, so no cursor. */
const POINTER_KINDS = new Set<string>(["click", "type", "key", "scroll"]);
/** Actions that change the page where Tilo acted: the picture before them, with the cursor, is shown as well. */
const TWO_PICTURES = new Set<string>(["click", "type", "key"]);

/** DEMO-BROWSER: every recorded step, oldest first, with its caption and cursor: what the panel can step through. */
export function browserFrames(events: readonly BrowserEvent[]): Frame[] {
  const frames: Frame[] = [];
  // The last recorded frame of the session: the page as it was before the next step.
  let previous: string | null = null;
  for (const event of events) {
    if (!event.data || typeof event.data !== "object") continue;
    if (event.type === "browser.started") {
      const data = event.data as BrowserStartedData;
      const id = data.frame?.artifact_id ?? null;
      previous = id;
      if (id)
        frames.push({
          artifactId: id,
          caption: `Opened ${data.host ?? "the browser"}`,
          cursor: null,
          host: data.host ?? null,
          before: null,
        });
    } else if (event.type === "browser.acted") {
      const data = event.data as BrowserActedData;
      const id = data.frame?.artifact_id;
      if (!id) continue;
      const caption = data.caption ?? event.summary ?? "Browser action";
      const box =
        (data.verdict === "done" || data.verdict === "gated") && POINTER_KINDS.has(data.kind)
          ? data.target_box
          : null;
      const cursor = box
        ? { seq: event.seq, x: box.x + box.width / 2, y: box.y + box.height / 2, caption }
        : null;
      const before = cursor && TWO_PICTURES.has(data.kind) ? previous : null;
      frames.push({ artifactId: id, caption, cursor, host: data.host ?? null, before });
      previous = id;
    }
  }
  return frames;
}

/** The pictures of the steps in order: a click, typed field or key press has its "before" (the previous frame, the
 * cursor where Tilo acted) and then its "after" (its own frame, the cursor where the mouse is now); the rest one. */
export function browserPictures(frames: readonly Frame[]): Picture[] {
  return frames.flatMap((frame, step): Picture[] =>
    frame.before
      ? [
          { step, artifactId: frame.before, phase: "before" },
          { step, artifactId: frame.artifactId, phase: "after" },
        ]
      : [{ step, artifactId: frame.artifactId, phase: null }],
  );
}

/** The session's state, from recorded events only. */
export function browserView(events: readonly BrowserEvent[]): {
  session: string | null;
  stopped: boolean;
  gated: boolean;
  host: string | null;
  paused: boolean;
  outcome: string | null;
  refusal: string | null;
  busy: boolean;
} {
  let session: string | null = null;
  let stopped = false;
  let gated = false;
  let host: string | null = null;
  let paused = false;
  let outcome: string | null = null;
  let refusal: string | null = null;
  let busy = false; // the newest event after the session's last step is the browser's busy line
  for (const event of events) {
    if (session && event.type === "agent.working") {
      busy = event.summary === BUSY_LINE;
      continue;
    }
    if (session && event.type === "world.paused") {
      paused = true;
      continue;
    }
    if (session && event.type === "world.resumed") {
      paused = false;
      continue;
    }
    if (!event.data || typeof event.data !== "object") continue;
    if (event.type === "browser.started") {
      const data = event.data as BrowserStartedData;
      session = data.session;
      host = data.host;
      stopped = false;
      gated = false;
      paused = false;
      outcome = null;
      refusal = null;
      busy = false;
    } else if (event.type === "browser.acted") {
      const data = event.data as BrowserActedData;
      if (session !== data.session) continue;
      busy = false;
      host = data.host ?? host;
      if (data.verdict === "gated") gated = true;
      if (data.verdict === "refused" && data.reason && data.reason in REFUSAL_LINES)
        refusal = data.reason;
    } else if (event.type === "browser.stopped") {
      const data = event.data as BrowserStoppedData;
      if (session === data.session) {
        stopped = true;
        outcome = data.outcome ?? null;
      }
    }
  }
  return { session, stopped, gated, host, paused, outcome, refusal, busy };
}

type Phase = "live" | "paused" | "waiting" | "finished" | "stopped";

function phaseOf(view: ReturnType<typeof browserView>): Phase {
  if (view.gated) return "waiting";
  if (view.paused) return "paused";
  if (!view.stopped) return "live";
  return view.refusal || (view.outcome && view.outcome !== "done") ? "stopped" : "finished";
}

const BADGE: Record<Phase, string> = {
  live: "Live",
  paused: "Paused",
  waiting: "Waiting for you",
  finished: "Finished",
  stopped: "Stopped",
};

export function BrowserPanel({
  client,
  worldId,
  events,
  replay,
  placement = "inline",
}: {
  client: TiloClient;
  worldId: string;
  events: readonly BrowserEvent[];
  replay: boolean;
  /** "takeover": fills the World's map area (its parent is positioned), with a way back to the map, and the person can
   * drag it into a floating window. "page": fills its own page (its parent is positioned and has a height). */
  placement?: "inline" | "takeover" | "page";
}) {
  const view = browserView(events);
  const frames = browserFrames(events);
  const pictures = browserPictures(frames);
  const reader = client as FrameClient;
  // Display state only: which recorded picture is shown (null follows the newest), the enlarged view, the session the
  // person went back to the map from (the next session the browser opens shows itself again) and, once dragged, where
  // the floating window sits (null: docked over the map).
  const [pick, setPick] = useState<number | null>(null);
  const [enlarged, setEnlarged] = useState(false);
  const [mapFor, setMapFor] = useState<string | null>(null);
  const [place, setPlace] = useState<FloatPos | null>(readPos);
  const [box, setBox] = useState<Size>({ w: FLOAT_WIDTH, h: 640 });
  const win = useWindowSize();
  const index = pick === null ? pictures.length - 1 : Math.min(pick, pictures.length - 1);
  const shown = index >= 0 ? pictures[index] : undefined;
  const stepAt = shown?.step ?? -1;
  const current = stepAt >= 0 ? frames[stepAt] : undefined;
  const frameId = shown?.artifactId ?? null;
  const [image, setImage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [size, setSize] = useState({ width: 1200, height: 800 });
  const [request, setRequest] = useState<"idle" | "stopping" | "error">("idle");
  useEffect(() => {
    setImage(null);
    setFailed(false);
    if (!frameId || !reader.getBrowserFrame || replay) return;
    let active = true;
    let url: string | null = null;
    reader
      .getBrowserFrame(worldId, frameId)
      .then((blob) => {
        if (!active) return;
        url = URL.createObjectURL(blob);
        setImage(url);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [reader, worldId, frameId, replay]);
  useEffect(() => {
    if (!enlarged) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setEnlarged(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [enlarged]);
  // The enlarged picture is a modal dialog in the top layer, so no map, header or container clips or covers it.
  // Closing it puts focus back on the picture that opened it.
  const zoom = useRef<HTMLDialogElement>(null);
  const shot = useRef<HTMLButtonElement>(null);
  const wasEnlarged = useRef(false);
  useLayoutEffect(() => {
    const el = zoom.current;
    if (!el || el.open) return;
    if (typeof el.showModal === "function") el.showModal();
    else el.setAttribute("open", "");
  });
  useEffect(() => {
    if (wasEnlarged.current && !enlarged) shot.current?.focus();
    wasEnlarged.current = enlarged;
  }, [enlarged]);
  // The step list keeps the shown step and the one before it in view, moving as little as it can (a jump, never a
  // scroll animation), so a long run's newest step is seen. Only a change of step or coming back from the map moves it,
  // never a poll or the person's own scroll.
  const strip = useRef<HTMLOListElement>(null);
  const onMap = mapFor !== null && mapFor === view.session;
  useLayoutEffect(() => {
    const list = strip.current;
    const items = list?.querySelectorAll<HTMLElement>("li > button");
    const item = items?.[stepAt];
    if (!list || !items || !item || onMap) return;
    const before = items[stepAt - 1] ?? item;
    const keep = (from: number, to: number, scrolled: number, room: number) =>
      from < scrolled ? from : to > scrolled + room ? Math.max(from, to - room) : scrolled;
    list.scrollLeft = keep(
      before.offsetLeft - list.offsetLeft,
      item.offsetLeft - list.offsetLeft + item.offsetWidth,
      list.scrollLeft,
      list.clientWidth,
    );
    list.scrollTop = keep(
      before.offsetTop - list.offsetTop,
      item.offsetTop - list.offsetTop + item.offsetHeight,
      list.scrollTop,
      list.clientHeight,
    );
  }, [stepAt, onMap]);
  // The window on the World page (owner, 21 Oct: "see the world while the browser works"): a solid card in the map's
  // corner, the map round it; Expand makes it take over the map area and Shrink makes it a card again; dragging its bar
  // (or the arrow keys on the grip) makes it a floating card anywhere on screen, at the place saved for this viewer, and
  // Dock puts it back in the corner. A phone-wide view always takes the map area over, with no drag.
  const takeover = placement === "takeover";
  const canDrag = takeover && win.w >= DRAG_MIN_WIDTH;
  const floating = canDrag && place !== null;
  const [expanded, setExpanded] = useState(false);
  const inCorner = canDrag && !floating && !expanded;
  const root = useRef<HTMLElement>(null);
  const grip = useRef<HTMLButtonElement>(null);
  // Docking moves the card back into the page, a new element: the grip takes the focus once it is drawn there.
  const [docked, setDocked] = useState(false);
  useLayoutEffect(() => {
    if (!docked) return;
    grip.current?.focus();
    setDocked(false);
  }, [docked]);
  // A floating card is drawn in the Park root, not inside the page: the World page's entrance keeps a transform, which
  // would hold a fixed box inside the page (live 21 Oct: it sat 100px below its place and moved with the page). The root
  // still carries the theme's tokens.
  const [layer, setLayer] = useState<Element | null>(null);
  useLayoutEffect(() => {
    setLayer(document.querySelector("[data-park]"));
  }, []);
  useLayoutEffect(() => {
    const el = root.current;
    if (!el || !floating) return;
    const [w, h] = [el.offsetWidth, el.offsetHeight];
    setBox((b) => (b.w === w && b.h === h ? b : { w, h }));
  });
  const session = view.session;
  if (!session) return null;
  if (takeover && mapFor === session) {
    return (
      <button type="button" className="tilo-browser-chip" onClick={() => setMapFor(null)}>
        {`Show Tilo browser · ${frames.length} ${frames.length === 1 ? "step" : "steps"}`}
      </button>
    );
  }
  const phase = phaseOf(view);
  // The session is still open while it is live or waiting for the person: only then can Stop do anything.
  const open = (phase === "live" || phase === "waiting") && !replay;
  const canStop = open && Boolean(reader.stopBrowser) && request === "idle";
  // The cursor is the shown step's own (none for extract, navigate or the first page): where Tilo's mouse was.
  const cursor = current?.cursor ?? null;
  // Following the newest (no pick) shows the newest picture; a pick past the last one goes back to following it.
  const goTo = (to: number) => setPick(to >= pictures.length - 1 ? null : Math.max(0, to));
  // A step in the numbered list shows the page after it: its last picture.
  const goToStep = (step: number) => {
    const last = pictures.map((p) => p.step).lastIndexOf(step);
    if (last >= 0) goTo(last);
  };
  const handoffHost =
    view.host && /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(view.host) ? view.host : null;
  const address = current?.host ?? view.host ?? "";
  const side = shown?.phase ? ` · ${shown.phase}` : "";
  const stepLabel = current
    ? `Step ${stepAt + 1} of ${frames.length} · ${current.caption}${side}`
    : "";
  const at = floating && place ? clampPos(place, win, box) : null;
  // A move is clamped with the card and the window as they are now (the card's height changes with the picture and the
  // steps), not sizes from an earlier render; docked, the floating card's last known size stands in.
  const card = (): Size => {
    const el = root.current;
    return el?.classList.contains("tilo-bv--floating")
      ? { w: el.offsetWidth, h: el.offsetHeight }
      : box;
  };
  const screen = (): Size => ({ w: window.innerWidth, h: window.innerHeight });
  // The drag follows the pointer on the window, not on the bar: the first move moves the card into the Park root, a new
  // element, and the bar it started on is gone.
  const startDrag = (e: ReactPointerEvent<HTMLElement>) => {
    const onControl = (e.target as Element).closest("button:not(.tilo-bv__grip), a");
    if (!canDrag || e.button !== 0 || onControl) return;
    const rect = root.current?.getBoundingClientRect();
    if (!rect) return;
    // Docked, the window shrinks to its floating width under the pointer, so it starts centred on the pointer.
    const width = Math.min(FLOAT_WIDTH, win.w * 0.92);
    const from = at ?? { left: e.clientX - width / 2, top: rect.top };
    window.getSelection()?.removeAllRanges(); // words selected elsewhere would start the browser's own drag
    const start = { x: e.clientX, y: e.clientY };
    let to: FloatPos | null = null;
    const move = (ev: PointerEvent) => {
      const [dx, dy] = [ev.clientX - start.x, ev.clientY - start.y];
      if (!to && Math.hypot(dx, dy) < DRAG_FROM) return;
      to = clampPos({ left: from.left + dx, top: from.top + dy }, screen(), card());
      setExpanded(false);
      setPlace(to);
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      if (to) writePos(to);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  }; // Arrow keys on the grip move the window 16 px a press; the first press undocks it where it sits.
  const nudge = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    const by: Record<string, [number, number]> = {
      ArrowLeft: [-STEP, 0],
      ArrowRight: [STEP, 0],
      ArrowUp: [0, -STEP],
      ArrowDown: [0, STEP],
    };
    const d = by[e.key];
    const rect = root.current?.getBoundingClientRect();
    if (!d || !canDrag || !rect) return;
    e.preventDefault();
    const from = at ?? { left: rect.left, top: rect.top };
    const to = clampPos({ left: from.left + d[0], top: from.top + d[1] }, screen(), card());
    setExpanded(false);
    setPlace(to);
    writePos(to);
  };
  const dock = () => {
    setPlace(null);
    writePos(null);
    setDocked(true);
  };
  const expand = (wide: boolean) => {
    setPlace(null);
    writePos(null);
    setExpanded(wide);
  };
  const line =
    phase === "waiting"
      ? GATED_LINE
      : request === "stopping"
        ? "Stopping…"
        : phase === "paused"
          ? "The world is paused."
          : phase === "finished"
            ? finishedLine(frames.length)
            : phase === "stopped"
              ? (lineOf(REFUSAL_LINES, view.refusal) ??
                lineOf(STOP_LINES, view.outcome) ??
                STOP_LINES.error)
              : view.busy
                ? BUSY_LINE
                : DECIDING_LINE;
  const stop = () => {
    if (!canStop) return;
    const call = reader.stopBrowser?.(worldId, session);
    if (!call) return;
    setRequest("stopping");
    call.catch(() => setRequest("error"));
  };
  const placeholder = replay
    ? "Recorded pictures are not shown in a replay."
    : !frameId
      ? `Opening ${view.host ?? "the page"}…`
      : failed
        ? FRAME_UNAVAILABLE
        : "Loading the picture…";
  // The page and the expanded view share the fill-the-parent layout (the page adds its own border); the corner card and
  // the floating card are windows that size to their content.
  const classes = [
    "tilo-bv",
    (takeover && !inCorner && !floating) || placement === "page" ? "tilo-bv--takeover" : "",
    placement === "page" ? "tilo-bv--page" : "",
    inCorner || floating ? "tilo-bv--window" : "",
    inCorner ? "tilo-bv--card" : "",
    floating ? "tilo-bv--floating" : "",
  ];
  const panel = (
    <section
      ref={root}
      className={classes.filter(Boolean).join(" ")}
      style={
        at
          ? ({ left: at.left, top: at.top, "--tilo-bv-top": `${at.top}px` } as CSSProperties)
          : undefined
      }
      aria-label="Tilo browser"
      data-testid="tilo-browser-panel"
      data-phase={phase}
      data-floating={floating ? "true" : undefined}
    >
      <header
        className="tilo-bv__chrome"
        data-draggable={canDrag ? "true" : undefined}
        onPointerDown={startDrag}
      >
        {canDrag ? (
          <button
            ref={grip}
            type="button"
            className="tilo-bv__grip"
            aria-label="Move the browser"
            title="Drag the bar, or press the arrow keys here, to move the browser"
            onKeyDown={nudge}
          >
            <span aria-hidden="true">⋮⋮</span>
          </button>
        ) : null}
        <span className="tilo-bv__badge" data-phase={phase}>
          {BADGE[phase]}
        </span>
        <span className="tilo-bv__address" title={address}>
          {address || "Tilo browser"}
        </span>
        <span className="tilo-bv__actions">
          {canStop ? (
            <button type="button" className="tilo-bv__button" onClick={stop}>
              Stop
            </button>
          ) : null}
          {placement !== "page" && !replay ? (
            <a
              className="tilo-bv__button tilo-bv__newtab"
              href={browserPath(worldId)}
              target="_blank"
              rel="noopener noreferrer"
            >
              Open in new tab
            </a>
          ) : null}
          {canDrag ? (
            <button type="button" className="tilo-bv__button" onClick={() => expand(!expanded)}>
              {expanded ? "Shrink" : "Expand"}
            </button>
          ) : null}
          {floating ? (
            <button type="button" className="tilo-bv__button" onClick={dock}>
              Dock
            </button>
          ) : null}
          {takeover ? (
            <button type="button" className="tilo-bv__button" onClick={() => setMapFor(session)}>
              Back to map
            </button>
          ) : null}
        </span>
      </header>
      <div className="tilo-bv__body">
        <figure className="tilo-bv__frame">
          {image ? (
            <button
              ref={shot}
              type="button"
              className="tilo-bv__shot"
              aria-label="Enlarge the picture"
              onClick={() => setEnlarged(true)}
            >
              <img
                src={image}
                alt={`What Tilo's browser showed: ${current?.caption ?? "page"}`}
                onLoad={(e) =>
                  setSize({
                    width: e.currentTarget.naturalWidth,
                    height: e.currentTarget.naturalHeight,
                  })
                }
              />
              {cursor ? (
                <span
                  className="tilo-browser__cursor"
                  data-testid="tilo-browser-cursor"
                  data-event-seq={cursor.seq}
                  data-picture={shown?.phase ?? undefined}
                  style={{
                    left: `${(cursor.x / size.width) * 100}%`,
                    top: `${(cursor.y / size.height) * 100}%`,
                  }}
                >
                  <span>Tilo</span>
                </span>
              ) : null}
            </button>
          ) : (
            <div className="tilo-bv__shot tilo-bv__shot--empty">
              <p>{placeholder}</p>
            </div>
          )}
          <figcaption className="tilo-bv__label">{stepLabel}</figcaption>
        </figure>
        {frames.length > 0 ? (
          <ol ref={strip} className="tilo-bv__steps" aria-label="Browser steps">
            {frames.map((frame, i) => (
              <li key={frame.artifactId}>
                <button
                  type="button"
                  aria-current={i === stepAt ? "step" : undefined}
                  aria-label={`Step ${i + 1}: ${frame.caption}`}
                  onClick={() => goToStep(i)}
                >
                  <span className="tilo-bv__num">{i + 1}</span>
                  <span className="tilo-bv__stepname">{frame.caption}</span>
                </button>
              </li>
            ))}
          </ol>
        ) : null}
      </div>
      <footer className="tilo-bv__bar">
        <p className="tilo-bv__line" aria-live="polite">
          {line}
        </p>
        <span className="tilo-bv__nav">
          {pictures.length > 1 ? (
            <>
              <button
                type="button"
                className="tilo-bv__button tilo-bv__earlier"
                disabled={index <= 0}
                onClick={() => goTo(index - 1)}
              >
                Earlier
              </button>
              <button
                type="button"
                className="tilo-bv__button tilo-bv__later"
                disabled={index >= pictures.length - 1}
                onClick={() => goTo(index + 1)}
              >
                Later
              </button>
              {pick !== null ? (
                <button
                  type="button"
                  className="tilo-bv__button tilo-bv__latest"
                  onClick={() => setPick(null)}
                >
                  Latest
                </button>
              ) : null}
            </>
          ) : null}
        </span>
      </footer>
      {phase === "waiting" && handoffHost ? (
        <a
          className="tilo-bv__handoff"
          href={`https://${handoffHost}/`}
          target="_blank"
          rel="noopener noreferrer"
        >
          {`Open ${handoffHost} yourself`}
        </a>
      ) : null}
      {request === "error" ? (
        <p role="alert">Tilo could not confirm the stop, so try again.</p>
      ) : null}
      {enlarged && image ? (
        // biome-ignore lint/a11y/useKeyWithClickEvents: a click-away scrim; Escape and the Close button are the keyboard way out
        <dialog
          ref={zoom}
          className="tilo-bv__zoom"
          aria-label="Enlarged browser picture"
          onClose={() => setEnlarged(false)}
          onClick={(e) => {
            if (e.target === e.currentTarget) setEnlarged(false);
          }}
        >
          <div className="tilo-bv__zoombox">
            <div className="tilo-bv__zoomhead">
              <span>{stepLabel}</span>
              <button type="button" className="tilo-bv__button" onClick={() => setEnlarged(false)}>
                Close
              </button>
            </div>
            <img src={image} alt={`Full size: ${current?.caption ?? "page"}`} />
          </div>
        </dialog>
      ) : null}
    </section>
  );
  return floating && layer ? createPortal(panel, layer) : panel;
}
