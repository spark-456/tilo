import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, authToken } from "../api/ClientProvider";

export interface WebsiteArtifactVersion {
  readonly artifact_id: string;
  readonly version: number;
  readonly title: string;
  readonly content_sha256: string;
  readonly media_type?: string;
}

const bytesToHex = (bytes: ArrayBuffer): string =>
  Array.from(new Uint8Array(bytes), (value) => value.toString(16).padStart(2, "0")).join("");

function safeFilename(title: string): string {
  const safe = Array.from(title, (character) => {
    const code = character.codePointAt(0) ?? 0;
    return code < 32 || /[<>:"/\\|?*]/.test(character) ? " " : character;
  })
    .join("")
    .trim()
    .replace(/\s+/g, " ");
  return `${safe || "website"}.html`;
}

export function WebsitePreview({
  worldId,
  artifact,
  initialBlob,
  isSignedIn: propIsSignedIn,
}: {
  readonly worldId: string;
  readonly artifact: WebsiteArtifactVersion;
  readonly initialBlob?: Blob | null;
  readonly isSignedIn?: boolean;
}) {
  const [html, setHtml] = useState<string | null>(null);
  const [fileBytes, setFileBytes] = useState<ArrayBuffer | null>(null);
  const [failure, setFailure] = useState<"load" | "hash" | "timeout" | "navigation" | null>(null);
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [isSignedIn, setIsSignedIn] = useState(propIsSignedIn ?? false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);

  const sectionRef = useRef<HTMLElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const htmlRef = useRef<string | null>(null);
  const writtenRef = useRef(false);
  const sentRef = useRef(false);
  const writtenTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    if (propIsSignedIn !== undefined) {
      setIsSignedIn(propIsSignedIn);
      return;
    }
    let active = true;
    const checkAuth = async () => {
      try {
        const token = await authToken?.();
        if (active) setIsSignedIn(Boolean(token));
      } catch {
        if (active) setIsSignedIn(false);
      }
    };
    void checkAuth();
    return () => {
      active = false;
    };
  }, [propIsSignedIn]);

  useEffect(() => {
    const onFsChange = () => {
      setIsFullScreen(Boolean(document.fullscreenElement));
    };
    document.addEventListener("fullscreenchange", onFsChange);
    return () => document.removeEventListener("fullscreenchange", onFsChange);
  }, []);

  const toggleFullScreen = async () => {
    try {
      if (!document.fullscreenElement) {
        if (sectionRef.current?.requestFullscreen) {
          await sectionRef.current.requestFullscreen();
        } else {
          setIsFullScreen(true);
        }
      } else {
        if (document.exitFullscreen) {
          await document.exitFullscreen();
        } else {
          setIsFullScreen(false);
        }
      }
    } catch {
      setIsFullScreen((prev) => !prev);
    }
  };

  const copyLink = async () => {
    if (!isSignedIn) return;
    try {
      const link = window.location.href;
      await navigator.clipboard.writeText(link);
      setCopyStatus("Link copied");
    } catch {
      setCopyStatus("Copy unavailable");
    }
  };

  useEffect(() => {
    let active = true;
    setHtml(null);
    setFileBytes(null);
    setFailure(null);
    if (writtenTimeoutRef.current !== null) window.clearTimeout(writtenTimeoutRef.current);
    writtenTimeoutRef.current = null;
    writtenRef.current = false;
    sentRef.current = false;
    htmlRef.current = null;
    const read = async (): Promise<void> => {
      try {
        let content: ArrayBuffer;
        if (initialBlob) {
          content = await initialBlob.arrayBuffer();
        } else {
          const token = await authToken?.();
          const origin = API_URL?.replace(/\/+$/, "");
          if (!origin || !token) throw new Error("unavailable");
          const query = new URLSearchParams({
            artifact: artifact.artifact_id,
            version: String(artifact.version),
          });
          const response = await fetch(
            `${origin}/worlds/${encodeURIComponent(worldId)}/result?${query.toString()}`,
            { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
          );
          if (!response.ok) throw new Error("unavailable");
          content = await response.arrayBuffer();
        }
        const actual = bytesToHex(await crypto.subtle.digest("SHA-256", content));
        if (!active) return;
        if (artifact.content_sha256 && actual !== artifact.content_sha256.toLowerCase()) {
          setFailure("hash");
          return;
        }
        const text = new TextDecoder("utf-8", { fatal: true }).decode(content);
        htmlRef.current = text;
        setFileBytes(content);
        setHtml(text);
      } catch {
        if (active) setFailure("load");
      }
    };
    void read();
    return () => {
      active = false;
      if (writtenTimeoutRef.current !== null) window.clearTimeout(writtenTimeoutRef.current);
      writtenTimeoutRef.current = null;
    };
  }, [worldId, artifact.artifact_id, artifact.version, artifact.content_sha256, initialBlob]);

  const sendPreview = useCallback(() => {
    const target = frameRef.current?.contentWindow;
    const text = htmlRef.current;
    if (sentRef.current || !target || text === null) return;
    sentRef.current = true;
    target.postMessage({ tilo: "preview", html: text }, "*");
    writtenTimeoutRef.current = window.setTimeout(() => {
      if (writtenRef.current) return;
      setHtml(null);
      setFailure("timeout");
    }, 8_000);
  }, []);

  useEffect(() => {
    const onMessage = (event: MessageEvent): void => {
      if (
        event.source !== frameRef.current?.contentWindow ||
        event.origin !== "null" ||
        event.data?.tilo !== "preview-written" ||
        writtenRef.current
      )
        return;
      writtenRef.current = true;
      if (writtenTimeoutRef.current !== null) window.clearTimeout(writtenTimeoutRef.current);
      writtenTimeoutRef.current = null;
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const download = (): void => {
    if (fileBytes === null) return;
    const blob = new Blob([fileBytes], { type: "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = safeFilename(artifact.title);
      document.body.append(link);
      try {
        link.click();
      } finally {
        link.remove();
      }
    } finally {
      URL.revokeObjectURL(url);
    }
  };

  const loaded = (): void => {
    if (writtenRef.current) {
      setHtml(null);
      setFailure("navigation");
      return;
    }
    sendPreview();
  };

  return (
    <section
      ref={sectionRef}
      aria-label="Website result"
      className={isFullScreen ? "tw-res-fullscreen" : undefined}
      style={
        isFullScreen
          ? {
              position: "fixed",
              inset: 0,
              zIndex: 9999,
              background: "var(--bg-canvas, #ffffff)",
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              boxSizing: "border-box",
              width: "100vw",
              height: "100vh",
            }
          : undefined
      }
    >
      <h2>{artifact.title}</h2>
      <p>Version {artifact.version}</p>
      {failure === "hash" ? <p role="alert">This file changed, so it is not shown</p> : null}
      {failure === "load" ? <p role="alert">The website could not be loaded.</p> : null}
      {failure === "timeout" ? (
        <p role="alert">Preview unavailable, open the file instead.</p>
      ) : null}
      {failure === "navigation" ? (
        <p role="alert">This website tried to leave Tilo. The preview was closed.</p>
      ) : null}
      {html === null && failure === null ? <p>Loading website…</p> : null}
      {html !== null && failure === null ? (
        <iframe
          ref={frameRef}
          title={`Website preview, Version ${artifact.version}`}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          allow=""
          src={`${API_URL?.replace(/\/+$/, "")}/preview/website`}
          onLoad={loaded}
          style={
            isFullScreen ? { flex: 1, width: "100%", height: "100%", border: "none" } : undefined
          }
        />
      ) : null}
      <div className="tw-res-actions">
        <button
          type="button"
          aria-label={isFullScreen ? "Exit full screen" : "Open full screen"}
          className="tw-res-btn tw-res-btn--pri"
          onClick={toggleFullScreen}
        >
          {isFullScreen ? "Exit full screen" : "Open full screen"}
        </button>
        {isSignedIn ? (
          <button
            type="button"
            aria-label="Copy link"
            className="tw-res-btn tw-res-btn--sec"
            onClick={copyLink}
          >
            Copy link
          </button>
        ) : null}
        <button
          type="button"
          aria-label="Download website"
          title="Download as .html"
          className="tw-res-btn tw-res-btn--sec"
          disabled={fileBytes === null}
          onClick={download}
        >
          Download as .html
        </button>
      </div>
      {copyStatus ? <output className="park-world-sub">{copyStatus}</output> : null}
    </section>
  );
}
