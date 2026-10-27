// DEMO-BROWSER: Tilo's browser as a page of its own (/world/:id/browser), the address "Open in new tab" opens. It is the
// same panel fed the same way as the World page: the signed-in world client's recorded events (polled by the HTTP
// client) and its frame route, so it is the owner's only (a world the list does not carry as the person's own is the
// ordinary "Page not found"). Nothing here is new to the API and nothing is public.
import { useEffect, useState } from "react";
import type { AppCtx } from "../../app/AppCtx";
import { NotFound } from "../../app/NotFound";
import { useParkApi, useWorldClient } from "../../app/context";
import { PageTitle } from "../../app/pageTitle";
import { BrowserPanel } from "../../shared/BrowserPanel";
import { useRunEvents } from "./useRunEvents";

/** Said until the run records `browser.started`; the page then shows the browser by itself. */
export const BROWSER_NOT_OPEN =
  "Tilo's browser has not opened in this run yet. This page shows it as soon as it does.";

type Read = "loading" | "ok" | "missing" | "failed";

export function BrowserPage({ app, worldId }: { app: AppCtx; worldId: string }) {
  const api = useParkApi();
  const client = useWorldClient();
  const [read, setRead] = useState<Read>("loading");
  // The world list says whose a world is: only a live world the person owns has a browser to show here.
  useEffect(() => {
    let live = true;
    setRead("loading");
    api.getWorlds(app.dec, app.added).then(
      (r) => {
        if (!live) return;
        const mine = r.data.some((w) => w.id === worldId && w.access !== "team");
        setRead(r.source === "live" && mine ? "ok" : "missing");
      },
      () => {
        if (live) setRead("failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api, app.dec, app.added, worldId]);
  const events = useRunEvents(client, read === "ok" ? worldId : null);

  if (read === "loading") return <div className="tilo-bv-page" data-testid="park-page-browser" />;
  if (read === "missing" || !client) {
    return (
      <>
        <PageTitle title="Not found" />
        <NotFound go={app.go} />
      </>
    );
  }
  const opened = events.some((e) => e.type === "browser.started");
  return (
    <div className="tilo-bv-page" data-testid="park-page-browser" data-world-id={worldId}>
      <h1 className="tilo-bv-page__title" tabIndex={-1}>
        Tilo browser
      </h1>
      {read === "failed" ? (
        <p className="tilo-bv-page__empty">World data is unavailable.</p>
      ) : opened ? (
        <BrowserPanel
          client={client}
          worldId={worldId}
          events={events}
          replay={false}
          placement="page"
        />
      ) : (
        <p className="tilo-bv-page__empty" role="status">
          {BROWSER_NOT_OPEN}
        </p>
      )}
    </div>
  );
}
