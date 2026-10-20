import type { BrowserActedData, BrowserStartedData, BrowserStoppedData } from "@tilo/contracts";
import { useEffect, useState } from "react";
import type { TiloClient } from "../../api/client";
import "./BrowserPanel.css";

type FrameClient = TiloClient & {
  getBrowserFrame?: (worldId: string, artifactId: string) => Promise<Blob>;
  pauseWorld?: (worldId: string) => Promise<void>;
  stopBrowser?: (worldId: string, session: string) => Promise<void>;
};

type Cursor = { seq: number; x: number; y: number; caption: string };

/** The server would not serve a recorded frame (missing, or not screened clean): said once, never a spinner. */
export const FRAME_UNAVAILABLE = "This frame could not be shown.";

type Frame = { artifactId: string; caption: string; cursor: Cursor | null };

/** DEMO-BROWSER: every recorded frame, oldest first, with its caption and cursor: what the panel can step through. */
export function browserFrames(events: readonly BrowserEvent[]): Frame[] {
  const frames: Frame[] = [];
  for (const event of events) {
    if (!event.data || typeof event.data !== "object") continue;
    if (event.type === "browser.started") {
      const id = (event.data as BrowserStartedData).frame?.artifact_id;
      if (id)
        frames.push({
          artifactId: id,
          caption: event.summary ?? "Tilo opened the browser",
          cursor: null,
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
      frames.push({ artifactId: id, caption, cursor });
    }
  }
  return frames;
}
type BrowserEvent = { seq: number; type: string; data?: unknown; summary?: string };

/** A browser frame or cursor is displayed only when its recorded event exists. */
export function browserView(events: readonly BrowserEvent[]): {
  frame: string | null;
  cursor: Cursor | null;
  session: string | null;
  stopped: boolean;
  gated: boolean;
  host: string | null;
  paused: boolean;
} {
  let frame: string | null = null;
  let cursor: Cursor | null = null;
  let session: string | null = null;
  let stopped = false;
  let gated = false;
  let host: string | null = null;
  let paused = false;
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
    } else if (event.type === "browser.stopped") {
      const data = event.data as BrowserStoppedData;
      if (session === data.session) stopped = true;
    }
  }
  return { frame, cursor, session, stopped, gated, host, paused };
}

export function BrowserPanel({
  client,
  worldId,
  events,
  replay,
}: {
  client: TiloClient;
  worldId: string;
  events: readonly BrowserEvent[];
  replay: boolean;
}) {
  const view = browserView(events);
  const frames = browserFrames(events);
  const reader = client as FrameClient;
  // DEMO-BROWSER: which recorded frame is shown (display state only); null follows the newest one.
  const [pick, setPick] = useState<number | null>(null);
  const index = pick === null ? frames.length - 1 : Math.min(pick, frames.length - 1);
  const shown = index >= 0 ? frames[index] : undefined;
  const frameId = shown?.artifactId ?? null;
  const [image, setImage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [size, setSize] = useState({ width: 1200, height: 800 });
  const [request, setRequest] = useState<"idle" | "pausing" | "stopping" | "error">("idle");
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
  const session = view.session;
  if (!session) return null;
  const cursor = pick === null ? view.cursor : (shown?.cursor ?? null);
  const step = (to: number) => setPick(to >= frames.length - 1 ? null : Math.max(0, to));
  const available = !replay && !view.stopped && !view.paused;
  const handoffHost =
    view.host && /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(view.host) ? view.host : null;
  const control = (kind: "pause" | "stop") => {
    if (!available || request !== "idle") return;
    const call =
      kind === "pause" ? reader.pauseWorld?.(worldId) : reader.stopBrowser?.(worldId, session);
    if (!call) return;
    setRequest(kind === "pause" ? "pausing" : "stopping");
    call.catch(() => setRequest("error"));
  };
  return (
    <section className="tilo-browser" aria-label="Tilo browser" data-testid="tilo-browser-panel">
      <header className="tilo-browser__header">
        <strong>Tilo browser</strong>
        <div>
          <button
            type="button"
            disabled={!available || !reader.pauseWorld}
            onClick={() => control("pause")}
          >
            Pause
          </button>
          <button
            type="button"
            disabled={!available || !reader.stopBrowser}
            onClick={() => control("stop")}
          >
            Stop
          </button>
        </div>
      </header>
      <div className="tilo-browser__screen" aria-label="Masked browser screenshot">
        {image ? (
          <img
            src={image}
            alt="Masked browser page"
            onLoad={(e) =>
              setSize({
                width: e.currentTarget.naturalWidth,
                height: e.currentTarget.naturalHeight,
              })
            }
          />
        ) : (
          <p>
            {replay
              ? "Recorded frame unavailable in replay."
              : failed
                ? FRAME_UNAVAILABLE
                : "Loading recorded frame…"}
          </p>
        )}
        {image && cursor ? (
          <div
            className="tilo-browser__cursor"
            data-testid="tilo-browser-cursor"
            data-event-seq={cursor.seq}
            style={{
              left: `${(cursor.x / size.width) * 100}%`,
              top: `${(cursor.y / size.height) * 100}%`,
            }}
          >
            <span>Tilo</span>
          </div>
        ) : null}
      </div>
      <p className="tilo-browser__caption" aria-live="polite">
        {pick !== null && shown
          ? `Frame ${index + 1} of ${frames.length}: ${shown.caption}`
          : view.paused
            ? "World paused"
            : view.gated
              ? "Waiting for you. Tilo stopped before submitting."
              : view.stopped
                ? "Browser stopped"
                : request === "pausing"
                  ? "Pausing…"
                  : request === "stopping"
                    ? "Stopping…"
                    : (view.cursor?.caption ?? "Tilo opened the browser")}
      </p>
      {frames.length > 1 ? (
        <div className="tilo-browser__frames">
          <button type="button" disabled={index <= 0} onClick={() => step(index - 1)}>
            Earlier
          </button>
          <button
            type="button"
            disabled={index >= frames.length - 1}
            onClick={() => step(index + 1)}
          >
            Later
          </button>
          {pick !== null ? (
            <button type="button" onClick={() => setPick(null)}>
              Latest
            </button>
          ) : null}
        </div>
      ) : null}
      {view.gated && handoffHost ? (
        <a href={`https://${handoffHost}/`} target="_blank" rel="noopener noreferrer">
          Open this site yourself to continue
        </a>
      ) : null}
      {request === "error" ? <p role="alert">Browser control was not confirmed.</p> : null}
    </section>
  );
}
