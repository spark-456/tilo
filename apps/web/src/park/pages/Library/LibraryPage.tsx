// The Library page (OLD-UI-OUT wave 3, replacing the old S-13 and its Version history screen): what Tilo has made for
// you, and what it remembers. Deliverables are read from the API's own delivery records of the person's completed
// worlds (nothing is "finished" before its event, HR-1); the memory layers are PRD 13.1's own words. No design export
// covers the page, so it is the Ledger's vocabulary in park tokens.
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { API_URL, appCheckToken, authToken, sessionView } from "../../../api/ClientProvider";
import { HttpClient } from "../../../api/http";
import { type Library, libraryApi } from "../../api/live/library";
import type { AppCtx } from "../../app/AppCtx";
import { Button, KpiTile, PageSheet } from "../../components";
import { EmptyState, ErrorState, LoadingState, StateAction } from "../../../design/tilo-t";
import "../../components/park.components.css";
import "./Library.css";

export interface LibraryPageProps {
  app: AppCtx;
}

// PRD 13.1 memory layers: what each holds and when it may be reused.
const LAYERS: ReadonlyArray<readonly [string, string]> = [
  ["Working memory", "The run's plan, artifacts and notes. This run only."],
  ["Result cache", "Tool results and extracted tables. Fresh for 7 days, never email bodies."],
  ["Artifact memory", "Past deliverables. Offered as a starting point, never silently reused."],
  ["Decisions", "Answers from you and Team Leads. They answer repeat questions."],
  ["Preferences", "Your settings and triage corrections. Applied in planning and drafting."],
  ["Skills", "Expert skills and versions. Loaded when a task needs them."],
];

export type State =
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "error" }
  | { status: "ready"; library: Library };

const words = (s: string): string => s.replace(/[_-]+/g, " ").replace(/^./, (c) => c.toUpperCase());

function Frame({ children }: { children?: ReactNode }) {
  return (
    <div className="park-library-root" data-testid="park-page-library">
      <PageSheet gap={20}>{children}</PageSheet>
    </div>
  );
}

function useLibrary(): { state: State; retry: () => void } {
  const demo = sessionView.demo();
  const api = useMemo(
    () =>
      API_URL?.trim() && !demo
        ? libraryApi(new HttpClient({ baseUrl: API_URL, appCheckToken, authToken }))
        : null,
    [demo],
  );
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<State>({ status: api ? "loading" : "unavailable" });
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt is the explicit retry trigger.
  useEffect(() => {
    if (!api) {
      setState({ status: "unavailable" });
      return;
    }
    let live = true;
    setState({ status: "loading" });
    api.getLibrary().then(
      (library) => live && setState({ status: "ready", library }),
      () => live && setState({ status: "error" }),
    );
    return () => {
      live = false;
    };
  }, [api, attempt]);
  return { state, retry: () => setAttempt((n) => n + 1) };
}

export function LibraryPage({ app }: LibraryPageProps) {
  const { state, retry } = useLibrary();
  return <LibraryView app={app} state={state} retry={retry} />;
}

/** The page for a given state: the hook above only supplies it, so every state is testable without a network. */
export function LibraryView({
  app,
  state,
  retry,
}: { app: AppCtx; state: State; retry: () => void }) {
  const [query, setQuery] = useState("");
  const head = (
    <div className="park-library-head">
      <h1 className="park-library-title">Library</h1>
      <p className="park-library-lede">
        What Tilo has made for you, and what it remembers for next time.
      </p>
    </div>
  );
  if (state.status === "loading") {
    return (
      <Frame>
        {head}
        <LoadingState layout="list" caption="Loading Library" />
      </Frame>
    );
  }
  if (state.status === "unavailable" || state.status === "error") {
    return (
      <Frame>
        {head}
        {state.status === "unavailable" ? (
          <EmptyState
            title="Not connected yet"
            body="Finished work shows here once you are signed in with a live workspace."
          />
        ) : (
          <ErrorState
            title="The Library could not load"
            body="Nothing was changed. Try again in a moment."
            action={
              <StateAction onClick={retry} icon="refresh">
                Try again
              </StateAction>
            }
          />
        )}
      </Frame>
    );
  }
  const { library } = state;
  const q = query.trim().toLowerCase();
  const shown = library.items.filter(
    (i) => q === "" || i.title.toLowerCase().includes(q) || i.worldTitle.toLowerCase().includes(q),
  );
  const worlds = new Set(library.items.map((i) => i.worldId)).size;
  return (
    <Frame>
      {head}
      <div className="park-library-kpis">
        <KpiTile
          label="Deliverables"
          value={String(library.items.length)}
          sub={library.items.length === 0 ? "None yet" : "Delivered"}
          {...(library.items.length > 0 ? { tone: "ok" as const } : {})}
        />
        <KpiTile label="Worlds with output" value={String(worlds)} />
      </div>
      <section className="park-library-card" aria-label="Deliverables">
        <div className="park-library-cardhead">
          <h2 className="park-library-cardtitle">Deliverables</h2>
          <input
            type="search"
            className="park-library-search"
            aria-label="Search the library"
            placeholder="Search the library"
            autoComplete="off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {library.items.length === 0 ? (
          <div data-testid="library-empty">
            <EmptyState
              title="Nothing delivered yet"
              body="Finished work is listed here as each one is delivered."
            />
          </div>
        ) : shown.length === 0 ? (
          <p className="park-library-note" data-testid="library-nomatch">
            No deliverable matches that search.
          </p>
        ) : (
          <ul className="park-library-list" data-testid="library-rows">
            {shown.map((i) => (
              <li key={`${i.worldId}:${i.artifactId}`} className="park-library-row">
                <div className="park-library-rowmain">
                  <span className="park-library-rowname">{i.title}</span>
                  <span className="park-library-rowsub">
                    {`${words(i.kind)} · version ${i.version} · ${i.worldTitle}`}
                  </span>
                </div>
                <Button variant="secondary" onClick={() => app.go("world", { id: i.worldId })}>
                  Open world
                </Button>
              </li>
            ))}
          </ul>
        )}
        {library.unreadable > 0 ? (
          <output className="park-library-note">
            {`${library.unreadable} finished world${library.unreadable === 1 ? "" : "s"} could not be read just now.`}
          </output>
        ) : null}
        {library.truncated ? (
          <p className="park-library-note">Showing the most recent finished worlds.</p>
        ) : null}
      </section>
      <section className="park-library-card" aria-label="Memory">
        <div className="park-library-cardhead">
          <h2 className="park-library-cardtitle">What Tilo remembers</h2>
        </div>
        <p className="park-library-note">
          Tilo reuses a result only after a check accepts it. Forgetting an item is not available
          yet.
        </p>
        <ul className="park-library-list">
          {LAYERS.map(([layer, what]) => (
            <li key={layer} className="park-library-row">
              <div className="park-library-rowmain">
                <span className="park-library-rowname">{layer}</span>
                <span className="park-library-rowsub">{what}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </Frame>
  );
}
