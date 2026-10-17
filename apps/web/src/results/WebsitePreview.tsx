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
}: {
  readonly worldId: string;
  readonly artifact: WebsiteArtifactVersion;
}) {
  const [html, setHtml] = useState<string | null>(null);
  const [fileBytes, setFileBytes] = useState<ArrayBuffer | null>(null);
  const [failure, setFailure] = useState<"load" | "hash" | "timeout" | null>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const htmlRef = useRef<string | null>(null);
  const writtenRef = useRef(false);
  const sentRef = useRef(false);
  const writtenTimeoutRef = useRef<number | null>(null);

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
        const content = await response.arrayBuffer();
        const actual = bytesToHex(await crypto.subtle.digest("SHA-256", content));
        if (!active) return;
        if (actual !== artifact.content_sha256.toLowerCase()) {
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
  }, [worldId, artifact.artifact_id, artifact.version, artifact.content_sha256]);

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
    sendPreview();
  };

  return (
    <section aria-label="Website result">
      <h2>{artifact.title}</h2>
      <p>Version {artifact.version}</p>
      {failure === "hash" ? <p role="alert">This file changed, so it is not shown</p> : null}
      {failure === "load" ? <p role="alert">The website could not be loaded.</p> : null}
      {failure === "timeout" ? (
        <p role="alert">Preview unavailable, open the file instead.</p>
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
        />
      ) : null}
      <button
        type="button"
        aria-label="Download website"
        disabled={fileBytes === null}
        onClick={download}
      >
        Download
      </button>
    </section>
  );
}
