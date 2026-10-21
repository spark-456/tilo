// DEMO-BROWSER: Tilo's browser as the person sees it. Every picture, caption and cursor comes from a recorded
// browser.started / browser.acted / browser.stopped event (HR-1); which picture is shown, enlarging it and going back to
// the map are display state only. On the World page it takes over the map area while the run has a browser session
// ("takeover"); elsewhere it is a card in the page ("inline").
import type { BrowserActedData, BrowserStartedData, BrowserStoppedData } from "@tilo/contracts";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { TiloClient } from "../../api/client";
import "./BrowserPanel.css";

type FrameClient = TiloClient & {
  getBrowserFrame?: (worldId: string, artifactId: string) => Promise<Blob>;
  stopBrowser?: (worldId: string, session: string) => Promise<void>;
};

type Cursor = { seq: number; x: number; y: number; caption: string };

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

/** A commit the browser stopped before (BR-05). */
export const GATED_LINE =
  "Tilo stopped before submitting anything, so open the site yourself to finish this step.";

/** The finished state: how many recorded steps there are to replay. */
export const finishedLine = (steps: number) =>
  `Finished: ${steps} ${steps === 1 ? "step" : "steps"}; pick any step to see it again.`;

const lineOf = (lines: Readonly<Record<string, string>>, key: string | null): string | undefined =>
  key ? lines[key] : undefined;

type Frame = { artifactId: string; caption: string; cursor: Cursor | null; host: string | null };

type BrowserEvent = { seq: number; type: string; data?: unknown; summary?: string };

/** DEMO-BROWSER: every recorded frame, oldest first, with its caption and cursor: what the panel can step through. */
export function browserFrames(events: readonly BrowserEvent[]): Frame[] {
  const frames: Frame[] = [];
  for (const event of events) {
    if (!event.data || typeof event.data !== "object") continue;
    if (event.type === "browser.started") {
      const data = event.data as BrowserStartedData;
      const id = data.frame?.artifact_id;
      if (id)
        frames.push({
          artifactId: id,
          caption: `Opened ${data.host ?? "the browser"}`,
          cursor: null,
          host: data.host ?? null,
        });
    } else if (event.type === "browser.acted") {
      const data = event.data as BrowserActedData;
      const id = data.frame?.artifact_id;
      if (!id) continue;
      const caption = data.caption ?? event.summary ?? "Browser action";
      const box = data.verdict === "done" ? data.target_box : null;
      const cursor = box
        ? { seq: event.seq, x: box.x + box.width / 2, y: box.y + box.height / 2, caption }
        : null;
      frames.push({ artifactId: id, caption, cursor, host: data.host ?? null });
    }
  }
  return frames;
}

/** A browser frame or cursor is displayed only when its recorded event exists. */
export function browserView(events: readonly BrowserEvent[]): {
  frame: string | null;
  cursor: Cursor | null;
  session: string | null;
  stopped: boolean;
  gated: boolean;
  host: string | null;
  paused: boolean;
  outcome: string | null;
  refusal: string | null;
} {
  let frame: string | null = null;
  let cursor: Cursor | null = null;
  let session: string | null = null;
  let stopped = false;
  let gated = false;
  let host: string | null = null;
  let paused = false;
  let outcome: string | null = null;
  let refusal: string | null = null;
  for (const event of events) {
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
      frame = data.frame?.artifact_id ?? null;
      cursor = null;
      stopped = false;
      gated = false;
      paused = false;
      outcome = null;
      refusal = null;
    } else if (event.type === "browser.acted") {
      const data = event.data as BrowserActedData;
      if (session !== data.session) continue;
      host = data.host ?? host;
      frame = data.frame?.artifact_id ?? frame;
      const box = data.target_box;
      if (data.verdict === "done" && box) {
        cursor = {
          seq: event.seq,
          x: box.x + box.width / 2,
          y: box.y + box.height / 2,
          caption: data.caption ?? event.summary ?? "Browser action",
        };
      }
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
  return { frame, cursor, session, stopped, gated, host, paused, outcome, refusal };
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
  /** "takeover": fills the World's map area (its parent is positioned), with a way back to the map. */
  placement?: "inline" | "takeover";
}) {
  const view = browserView(events);
  const frames = browserFrames(events);
  const reader = client as FrameClient;
  // Display state only: which recorded frame is shown (null follows the newest), the enlarged view, and the session the
  // person went back to the map from (the next session the browser opens shows itself again).
  const [pick, setPick] = useState<number | null>(null);
  const [enlarged, setEnlarged] = useState(false);
  const [mapFor, setMapFor] = useState<string | null>(null);
  const index = pick === null ? frames.length - 1 : Math.min(pick, frames.length - 1);
  const shown = index >= 0 ? frames[index] : undefined;
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
  // The step list centres the shown step (a jump, never a scroll animation; the browser clamps at either end), so a long
  // run's newest step and its neighbours are seen. Only a change of step or coming back from the map moves it, never a
  // poll or the person's own scroll.
  const strip = useRef<HTMLOListElement>(null);
  const onMap = mapFor !== null && mapFor === view.session;
  useLayoutEffect(() => {
    const list = strip.current;
    const item = list?.querySelectorAll<HTMLElement>("li > button")[index];
    if (!list || !item || onMap) return;
    list.scrollLeft = item.offsetLeft - list.offsetLeft - (list.clientWidth - item.offsetWidth) / 2;
    list.scrollTop = item.offsetTop - list.offsetTop - (list.clientHeight - item.offsetHeight) / 2;
  }, [index, onMap]);
  const session = view.session;
  if (!session) return null;
  const takeover = placement === "takeover";
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
  const cursor = pick === null ? view.cursor : (shown?.cursor ?? null);
  const step = (to: number) => setPick(to >= frames.length - 1 ? null : Math.max(0, to));
  const handoffHost =
    view.host && /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(view.host) ? view.host : null;
  const address = shown?.host ?? view.host ?? "";
  const stepLabel = shown ? `Step ${index + 1} of ${frames.length} · ${shown.caption}` : "";
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
              : "Tilo is using the browser now.";
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
  return (
    <section
      className={takeover ? "tilo-bv tilo-bv--takeover" : "tilo-bv"}
      aria-label="Tilo browser"
      data-testid="tilo-browser-panel"
      data-phase={phase}
    >
      <header className="tilo-bv__chrome">
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
                alt={`What Tilo's browser showed: ${shown?.caption ?? "page"}`}
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
                  aria-current={i === index ? "step" : undefined}
                  aria-label={`Step ${i + 1}: ${frame.caption}`}
                  onClick={() => step(i)}
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
          {frames.length > 1 ? (
            <>
              <button
                type="button"
                className="tilo-bv__button"
                disabled={index <= 0}
                onClick={() => step(index - 1)}
              >
                Earlier
              </button>
              <button
                type="button"
                className="tilo-bv__button"
                disabled={index >= frames.length - 1}
                onClick={() => step(index + 1)}
              >
                Later
              </button>
              {pick !== null ? (
                <button type="button" className="tilo-bv__button" onClick={() => setPick(null)}>
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
            <img src={image} alt={`Full size: ${shown?.caption ?? "page"}`} />
          </div>
        </dialog>
      ) : null}
    </section>
  );
}
