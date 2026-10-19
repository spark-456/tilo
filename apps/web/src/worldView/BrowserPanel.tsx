import type { BrowserActedData, BrowserStartedData, BrowserStoppedData } from "@tilo/contracts";
import { useEffect, useState } from "react";
import type { TiloClient } from "../api/client";
import "./BrowserPanel.css";

type FrameClient = TiloClient & {
  getBrowserFrame?: (worldId: string, artifactId: string) => Promise<Blob>;
  pauseWorld?: (worldId: string) => Promise<void>;
  stopBrowser?: (worldId: string, session: string) => Promise<void>;
};

type Cursor = { seq: number; x: number; y: number; caption: string };
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
  const reader = client as FrameClient;
  const [image, setImage] = useState<string | null>(null);
  const [size, setSize] = useState({ width: 1200, height: 800 });
  const [request, setRequest] = useState<"idle" | "pausing" | "stopping" | "error">("idle");
  useEffect(() => {
    setImage(null);
    if (!view.frame || !reader.getBrowserFrame || replay) return;
    let active = true;
    let url: string | null = null;
    reader
      .getBrowserFrame(worldId, view.frame)
      .then((blob) => {
        if (!active) return;
        url = URL.createObjectURL(blob);
        setImage(url);
      })
      .catch(() => {
        if (active) setImage(null);
      });
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [reader, worldId, view.frame, replay]);
  const session = view.session;
  if (!session) return null;
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
      <div className="tilo-browser__screen" aria-label="Latest masked browser screenshot">
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
          <p>{replay ? "Recorded frame unavailable in replay." : "Loading recorded frame…"}</p>
        )}
        {image && view.cursor ? (
          <div
            className="tilo-browser__cursor"
            data-testid="tilo-browser-cursor"
            data-event-seq={view.cursor.seq}
            style={{
              left: `${(view.cursor.x / size.width) * 100}%`,
              top: `${(view.cursor.y / size.height) * 100}%`,
            }}
          >
            <span>Tilo</span>
          </div>
        ) : null}
      </div>
      <p className="tilo-browser__caption" aria-live="polite">
        {view.paused
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
      {view.gated && handoffHost ? (
        <a href={`https://${handoffHost}/`} target="_blank" rel="noopener noreferrer">
          Open this site yourself to continue
        </a>
      ) : null}
      {request === "error" ? <p role="alert">Browser control was not confirmed.</p> : null}
    </section>
  );
}
