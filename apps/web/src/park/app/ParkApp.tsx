// The Park app (README "Routes", "The `app` prop", "Focus"): the data-park root around the shell (shell/AppShell:
// nav, backdrop, the one <main>, toast, world loader), the page for the route, the document title and the
// focus move after a route change. Lazy-imported by src/Root.tsx, so a landing visit never loads it (NFR-01).
import { type MouseEvent, Suspense, useEffect, useRef } from "react";
import { PageSheet } from "../components";
import { AppShell } from "../shell/AppShell";
import { ParkAuthProvider } from "../shell/auth";
import "../tokens/fonts";
import "../tokens/park.css";
import { type AppCtx, PAGE_LABEL } from "./AppCtx";
import "./park-app.css";
import { ParkProvider, usePageApp, useSessionAuth } from "./context";
import { PAGES } from "./pages";
import { isHomeAddress, useParkRoute } from "./router";

const NOT_FOUND_TITLE = "Page not found";

// The landing visit (`/`) is the Home page: its chunk request starts when the shell module is evaluated, not
// when the page first renders. `lazy()` in the registry reuses the same module, so nothing loads twice.
if (isHomeAddress()) void import("../pages/Home/HomePage");

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
        <a className="park-app__link" href="/" onClick={open}>
          Go to Home
        </a>
      </PageSheet>
    </div>
  );
}

/** Moves focus to the page heading when the route changes, never on the first load. */
// Suspense hides the page it is replacing with an inline `display: none` until the new chunk arrives.
const isHidden = (el: Element): boolean => el.closest('[style*="display: none"]') !== null;

function FocusHeading({ routeKey }: { routeKey: string }) {
  const last = useRef<string | null>(null);
  const mark = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (last.current === null || last.current === routeKey) {
      last.current = routeKey;
      return;
    }
    last.current = routeKey;
    const root = mark.current?.closest("main");
    if (!root) return;
    const left = document.activeElement;
    // The new page's heading, never the hidden one of the page it replaces.
    const focusHeading = (): boolean => {
      const heading = [...root.querySelectorAll("h1")].find((h) => !isHidden(h));
      if (!heading) return false;
      if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
      heading.focus();
      return true;
    };
    if (focusHeading()) return;
    // A lazy page's heading arrives with its chunk, or with its data. Focus it then, unless the person has
    // moved focus somewhere else in the meantime.
    const watch = new MutationObserver(() => {
      if (document.activeElement !== left) return watch.disconnect();
      if (focusHeading()) watch.disconnect();
    });
    watch.observe(root, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["style"],
    });
    return () => watch.disconnect();
  }, [routeKey]);
  // The shell owns the <main>; this marker (inside it) is how the heading is found.
  return <span ref={mark} hidden />;
}

function Shell() {
  const app = usePageApp();
  const route = useParkRoute();
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
    <div data-park data-time={app.time} data-motion={app.motion}>
      <AppShell>
        <Suspense fallback={null}>
          {Page ? <Page app={app} /> : <NotFound go={app.go} />}
          <FocusHeading routeKey={routeKey} />
        </Suspense>
      </AppShell>
    </div>
  );
}

export function ParkApp() {
  // FR-UX-10: the account menu reads the page's real sign-in; null (no sign-in here) keeps the prototype's behaviour.
  const auth = useSessionAuth();
  return (
    <ParkProvider>
      <ParkAuthProvider auth={auth}>
        <Shell />
      </ParkAuthProvider>
    </ParkProvider>
  );
}

export default ParkApp;
