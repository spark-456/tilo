import { useEffect, useRef, useState } from "react";
import { endpoint } from "./api";
import { captureHtml } from "./capture";

type App = { title: string; html: string };

export function PublicAppViewer({ handle, slug }: { handle: string; slug: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [app, setApp] = useState<App | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "missing">("loading");
  const [submit, setSubmit] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const path = `/public/apps/${encodeURIComponent(handle)}/${encodeURIComponent(slug)}`;

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    fetch(endpoint(path), { signal: controller.signal, credentials: "omit" })
      .then(async (response) => {
        if (!response.ok) throw new Error("unavailable");
        return (await response.json()) as App;
      })
      .then((value) => {
        setApp(value);
        setStatus("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("missing");
      });
    return () => controller.abort();
  }, [path]);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (
        event.source !== frame.current?.contentWindow ||
        event.data?.type !== "tilo-form-submit" ||
        submit === "saving"
      )
        return;
      const fields = event.data.fields;
      if (!fields || typeof fields !== "object" || Array.isArray(fields)) return;
      setSubmit("saving");
      void fetch(endpoint(`${path}/responses`), {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields, website: "" }),
      })
        .then((response) => {
          setSubmit(response.ok ? "saved" : "error");
        })
        .catch(() => setSubmit("error"));
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [path, submit]);

  if (status === "loading") return <main>Loading app…</main>;
  if (status === "missing" || !app)
    return (
      <main>
        <h1>This app is not available</h1>
      </main>
    );
  return (
    <div
      className="tilo-public-app"
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        fontFamily: "system-ui",
      }}
    >
      <header
        style={{
          padding: "12px 24px",
          borderBottom: "1px solid #ddd",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <strong>{app.title}</strong>
        <span>Made with Tilo</span>
      </header>
      {submit === "saved" && <output>Thank you! Your response was saved.</output>}
      {submit === "error" && <p role="alert">Your response was not saved. Please try again.</p>}
      <iframe
        ref={frame}
        title={app.title}
        sandbox="allow-scripts allow-forms"
        srcDoc={captureHtml(app.html)}
        style={{ width: "100%", flex: 1, minHeight: "75vh", border: 0 }}
      />
    </div>
  );
}
