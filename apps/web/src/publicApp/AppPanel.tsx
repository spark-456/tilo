import { useEffect, useRef, useState } from "react";
import { saveResult } from "../park/api/results";
import { signedAppFetch } from "./api";
import { captureHtml } from "./capture";
import "./publicApp.css";

type Row = { id: string; at: string; fields: Record<string, unknown> };
type Publication = { path: string; published: boolean };

export function AppPanel({
  artifactId,
  title,
  html,
}: { artifactId: string; title: string; html: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [publication, setPublication] = useState<Publication | null>(null);
  const [notice, setNotice] = useState("");
  const base = `/v1/artifacts/${encodeURIComponent(artifactId)}`;

  useEffect(() => {
    let active = true;
    void signedAppFetch(`${base}/responses`)
      .then(async (response) => {
        if (!response.ok) return;
        const data = (await response.json()) as { responses: Row[]; count: number };
        if (active) {
          setRows(data.responses);
          setCount(data.count);
        }
      })
      .catch(() => undefined);
    void signedAppFetch(`${base}/publish`)
      .then(async (response) => {
        if (response.ok && active)
          setPublication(((await response.json()) as { app: Publication }).app);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [base]);

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== frame.current?.contentWindow || event.data?.type !== "tilo-form-submit")
        return;
      const fields = event.data.fields;
      if (!fields || typeof fields !== "object" || Array.isArray(fields)) return;
      setNotice("Saving response…");
      void signedAppFetch(`${base}/responses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fields }),
      })
        .then(async (response) => {
          if (!response.ok) throw new Error("save_failed");
          const data = (await response.json()) as { count: number };
          setCount(data.count);
          setNotice("Thank you! Your response was saved.");
          void signedAppFetch(`${base}/responses`)
            .then(async (listing) => {
              if (!listing.ok) return;
              const updated = (await listing.json()) as { responses: Row[]; count: number };
              setRows(updated.responses);
              setCount(updated.count);
            })
            .catch(() => undefined);
        })
        .catch(() => setNotice("Your response could not be saved. Please try again."));
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, [base]);

  const publish = async (method: "POST" | "DELETE") => {
    setNotice("");
    try {
      const response = await signedAppFetch(`${base}/publish`, {
        method,
        ...(method === "POST"
          ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }
          : {}),
      });
      if (!response.ok) throw new Error("publish_failed");
      setPublication(((await response.json()) as { app: Publication }).app);
    } catch {
      setNotice(
        method === "POST"
          ? "This app could not be published. Please try again."
          : "This app could not be unpublished. Please try again.",
      );
    }
  };
  const csv = async () => {
    try {
      const response = await signedAppFetch(`${base}/responses.csv`);
      if (!response.ok) throw new Error("csv_failed");
      saveResult(await response.blob(), `${title}-responses`);
    } catch {
      setNotice("CSV could not be downloaded. Please try again.");
    }
  };
  const fields = [...new Set(rows.flatMap((row) => Object.keys(row.fields)))];

  return (
    <section aria-label={`${title} website`}>
      <h3>{title}</h3>
      <iframe
        ref={frame}
        title={`${title} preview`}
        sandbox="allow-scripts allow-forms"
        srcDoc={captureHtml(html)}
        className="tilo-app-preview"
      />
      {notice && <output>{notice}</output>}
      <p>
        <a href={`/app/${encodeURIComponent(artifactId)}`}>Open full page in Tilo</a>
      </p>
      <button
        type="button"
        onClick={() => saveResult(new Blob([html], { type: "text/html" }), title)}
      >
        Download HTML
      </button>
      {publication?.published ? (
        <div>
          <a href={publication.path} target="_blank" rel="noreferrer">
            {new URL(publication.path, location.origin).href}
          </a>
          <button
            type="button"
            onClick={() =>
              void navigator.clipboard.writeText(new URL(publication.path, location.origin).href)
            }
          >
            Copy link
          </button>
          <button type="button" onClick={() => void publish("DELETE")}>
            Unpublish
          </button>
        </div>
      ) : (
        <div>
          <p>Anyone with the link can open it and send answers. You can unpublish any time.</p>
          <button type="button" onClick={() => void publish("POST")}>
            Publish as a website
          </button>
        </div>
      )}
      {count !== null && <p>{count} responses</p>}
      <button type="button" onClick={() => void csv()}>
        Download CSV
      </button>
      <button type="button" disabled title="Drive saving is unavailable here">
        Save CSV to my Drive
      </button>
      {rows.length > 0 && (
        <div className="tilo-app-response-scroll">
          <table>
            <caption>Responses</caption>
            <thead>
              <tr>
                {fields.map((field) => (
                  <th key={field} scope="col">
                    {field}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 20).map((row) => (
                <tr key={row.id}>
                  {fields.map((field) => (
                    <td key={field}>{String(row.fields[field] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
