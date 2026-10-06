// The Park app shell (README "Routes", "The `app` prop", "Focus"): the data-park root, one <main> with
// the page for the route, the toast, the document title and the focus move after a route change.
// Lazy-imported by src/Root.tsx, so a landing visit never loads it (NFR-01).
import {
  type MouseEvent,
  type RefObject,
  Suspense,
  useEffect,
  useRef,
  useSyncExternalStore,
} from "react";
import { PageSheet, Toast } from "../components";
import "../tokens/park.css";
import { type AppCtx, PAGE_LABEL } from "./AppCtx";
import "./park-app.css";
import { ParkProvider, useApp, useParkStore } from "./context";
import { PAGES } from "./pages";
import { useParkRoute } from "./router";

const NOT_FOUND_TITLE = "Page not found";

function NotFound({ go }: { go: AppCtx["go"] }) {
  const open = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    go("home");
  };
  return (
    <div data-testid="park-not-found">
      <PageSheet>
        <h1 className="park-app__title" tabIndex={-1}>
          {NOT_FOUND_TITLE}
        </h1>
        <p className="park-app__note">There is no page at this address.</p>
        <a className="park-app__link" href="/park/home" onClick={open}>
          Go to Home
        </a>
      </PageSheet>
    </div>
  );
}

/** Moves focus to the page heading when the route changes, never on the first load. */
function FocusHeading({
  main,
  routeKey,
}: { main: RefObject<HTMLElement | null>; routeKey: string }) {
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (last.current === null || last.current === routeKey) {
      last.current = routeKey;
      return;
    }
    last.current = routeKey;
    const heading = main.current?.querySelector("h1");
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus();
  }, [main, routeKey]);
  return null;
}

function Shell() {
  const app = useApp();
  const store = useParkStore();
  const route = useParkRoute();
  const toast = useSyncExternalStore(store.subscribe, () => store.getState().toast);
  const main = useRef<HTMLElement>(null);
  const title = route ? PAGE_LABEL[route.page] : NOT_FOUND_TITLE;
  // A world is a different page per id; the other pages keep focus where it is when only a query changes.
  const routeKey = route
    ? route.page === "world"
      ? `world/${route.params.id}`
      : route.page
    : "none";
  useEffect(() => {
    const before = document.title;
    document.title = `${title} · Tilo`;
    return () => {
      document.title = before;
    };
  }, [title]);
  const Page = route ? PAGES[route.page] : null;
  return (
    <div data-park data-time={app.time}>
      <main ref={main} className="park-app__main">
        <Suspense fallback={null}>
          {Page ? <Page app={app} /> : <NotFound go={app.go} />}
          <FocusHeading main={main} routeKey={routeKey} />
        </Suspense>
      </main>
      {toast ? (
        <Toast
          message={toast.message}
          {...(toast.actionLabel !== undefined ? { actionLabel: toast.actionLabel } : {})}
          {...(toast.action !== undefined ? { onAction: toast.action } : {})}
          onDismiss={store.dismissToast}
        />
      ) : null}
    </div>
  );
}

export function ParkApp() {
  return (
    <ParkProvider>
      <Shell />
    </ParkProvider>
  );
}

export default ParkApp;
