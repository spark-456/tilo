// The frame every lens of one world shares (PRD 9.6, 18.3): the way back to the world's overview, the title, the
// World / Story / Trace tabs with the Delivery link, and the selection all of them share (FR-WLD-06). A Park page:
// the Park shell around it owns the navigation, the one <main> and the page heading focus.
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { useApp, useHasParkProvider, useParkApi } from "../park/app/context";
import { useRemote } from "../screens/remote";
import { findItem } from "../world/findItem";
import { useRunLog } from "../world/runLog";
import { useSelection } from "../world/selection";
import { ReplayNotices } from "./ReplayNotices";
import { ViewLink } from "./ViewLink";
import { type Lens, inspectPath, lensPath, overviewPath } from "./routes";

const TABS: ReadonlyArray<readonly [Lens, string]> = [
  ["stage", "World"],
  ["story", "Story"],
  ["trace", "Trace"],
];

/** The name the Park pages call this world, when they know it; null otherwise (the id never stands in for it). */
function useWorldName(worldId: string): string | null {
  const api = useParkApi();
  const app = useApp();
  const [name, setName] = useState<string | null>(null);
  const { dec, added } = app;
  useEffect(() => {
    let live = true;
    api.getWorlds(dec, added).then(
      (r) => {
        if (live) setName(r.data.find((w) => w.id === worldId)?.name ?? null);
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [api, dec, added, worldId]);
  return name;
}

/** FR-WLD-06: says which object the lenses follow, in words, and opens its Inspect page or clears it. It keeps one
 * height, so choosing or clearing moves nothing (CLS). */
export function SelectionBar({ worldId }: { worldId: string }) {
  const client = useClient();
  const events = useRunLog(client, worldId);
  const [layout] = useRemote("load the world", (signal) => client.getLayout(worldId, signal));
  const [id, set] = useSelection(worldId);
  const bar = useRef<HTMLDivElement>(null);
  const item = id && layout.status === "ready" ? findItem(layout.value, id, events) : null;
  return (
    <div
      className="park-view-selection"
      data-testid="selection-bar"
      data-selected-id={id ?? ""}
      // biome-ignore lint/a11y/useSemanticElements: a fieldset draws a border and legend; this labelled group only takes programmatic focus after Clear.
      role="group"
      aria-label="Selection"
      tabIndex={-1}
      ref={bar}
    >
      <span className="park-view-selection-text">
        {id ? (
          <>
            Selected: <b>{item?.name ?? id}</b>
            {item ? <small> {item.kind}</small> : null}
          </>
        ) : (
          "Choose anything to inspect it"
        )}
      </span>
      {id ? (
        <>
          <ViewLink className="park-view-chiplink" to={inspectPath(worldId, id)}>
            Inspect
          </ViewLink>
          <button
            type="button"
            className="park-view-chiplink"
            data-lens-control
            onClick={() => {
              set(null);
              // The Clear button goes away with the selection: focus moves to the bar, which stays (FR-WLD-11).
              bar.current?.focus();
            }}
          >
            Clear
          </button>
        </>
      ) : null}
    </div>
  );
}

/** Inside the Park app the crumb carries the world's name; with no Park provider (a lens drawn alone) it says
 * "World overview". */
function WorldName({ worldId }: { worldId: string }) {
  return useHasParkProvider() ? <ParkWorldName worldId={worldId} /> : <>World overview</>;
}
function ParkWorldName({ worldId }: { worldId: string }) {
  const name = useWorldName(worldId);
  return <>{name ?? "World overview"}</>;
}

export function LensFrame({
  worldId,
  current,
  title,
  children,
  hideTabs = false,
}: {
  worldId: string;
  current: Lens | "inspect" | "delivery";
  title: string;
  children: ReactNode;
  hideTabs?: boolean;
}) {
  return (
    <div className="park-view-root" data-testid={`park-view-${current}`}>
      <section className="park-sheet park-view-sheet">
        <div className="park-view-crumb">
          <ViewLink className="park-view-back" to={overviewPath(worldId)}>
            <span aria-hidden="true">‹</span> <WorldName worldId={worldId} />
          </ViewLink>
        </div>
        <header className="park-view-head">
          <h1 className="park-view-title" tabIndex={-1}>
            {title}
          </h1>
          {hideTabs ? null : (
            <nav className="park-view-tabs" aria-label="Lens">
              {TABS.map(([key, label]) => (
                <ViewLink
                  key={key}
                  to={lensPath(worldId, key)}
                  className="park-view-tab"
                  {...(key === current ? { "aria-current": "page" as const } : {})}
                >
                  {label}
                </ViewLink>
              ))}
              <ViewLink
                to={lensPath(worldId, "delivery")}
                className="park-view-tab"
                {...(current === "delivery" ? { "aria-current": "page" as const } : {})}
              >
                Delivery
              </ViewLink>
            </nav>
          )}
        </header>
        {hideTabs ? null : <SelectionBar worldId={worldId} />}
        {/* HR-4 and HR-6 on every world screen: the stage draws its own (it knows a ?fixture= replay's speed). */}
        {current === "stage" ? null : <ReplayNotices />}
        {children}
      </section>
    </div>
  );
}
