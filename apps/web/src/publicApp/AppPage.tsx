import { useEffect, useState } from "react";
import { AppPanel } from "./AppPanel";
import { signedAppFetch } from "./api";

export function AppPage({ artifactId }: { artifactId: string }) {
  const [data, setData] = useState<{ title: string; html: string } | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "missing">("loading");
  useEffect(() => {
    let active = true;
    setStatus("loading");
    void signedAppFetch(`/v1/artifacts/${encodeURIComponent(artifactId)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error("unavailable");
        return (await response.json()) as { title: string; html: string };
      })
      .then((value) => {
        if (active) {
          setData(value);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (active) setStatus("missing");
      });
    return () => {
      active = false;
    };
  }, [artifactId]);
  if (status === "loading")
    return (
      <main>
        <h1>Loading app…</h1>
      </main>
    );
  if (status === "missing" || !data)
    return (
      <main>
        <h1>This app is not available</h1>
      </main>
    );
  return (
    <main>
      <h1>{data.title}</h1>
      <AppPanel artifactId={artifactId} title={data.title} html={data.html} />
    </main>
  );
}
