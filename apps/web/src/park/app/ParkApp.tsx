// The Park app (README "Routes", "The `app` prop", "Focus"): the data-park root around the shell (shell/AppShell:
// nav, backdrop, the one <main>, toast, world loader), the page for the route, the document title and the
// focus move after a route change. Lazy-imported by src/Root.tsx, so a landing visit never loads it (NFR-01).
import {
  type ReactNode,
  Suspense,
  lazy,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { AppShell } from "../shell/AppShell";
import { ParkAuthProvider } from "../shell/auth";
import { useParkTour } from "../shell/tour";
import "../tokens/fonts";
import "../tokens/park.css";
import "../tokens/park.opaque.css";
import "../tokens/themes.css";
import "../studio/fonts";
import "../studio/studio.css";
import { DoodleGutter } from "../../design/tilo-t/DoodleGutter";
import "../../design/tilo-t/styles"; // TILO-T-FOUNDATION: tokens, Geist, keyframes, easing, reduced-motion
import { themeFor } from "../tokens/themes";
import { PAGE_LABEL } from "./AppCtx";
import { NotFound } from "./NotFound";
import "./park-app.css";
import "./mobile.css";
import { PendingWorldRoute } from "./PendingWorldRoute";
import { ParkProvider, usePageApp, useSessionAuth, useWorldClient } from "./context";
import { PageTitleContext } from "./pageTitle";
import { PAGES } from "./pages";
import { isHomeAddress, useBrowserRoute, useParkRoute, useQuizAppRoute } from "./router";

const QuizPlayerPage = lazy(() =>
  import("../pages/QuizPlayer/QuizPlayerPage").then((m) => ({ default: m.QuizPlayerPage })),
);
// DEMO-BROWSER: Tilo's browser as a page of its own (/world/:id/browser), the "Open in new tab" address.
const BrowserPage = lazy(() =>
  import("../pages/World/BrowserPage").then((m) => ({ default: m.BrowserPage })),
);

// The landing visit (`/`) is the Home page: its chunk request starts when the shell module is evaluated, not
// when the page first renders. `lazy()` in the registry reuses the same module, so nothing loads twice.
if (isHomeAddress()) void import("../pages/Home/HomePage");

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

/** A view the Root frames in this shell that is no Park page of its own (OLD-UI-OUT-2: a world's lenses, the
 * Needs-you page): its content, its tab title and a key that moves focus to its heading when it changes. */
export interface RoutedView {
  readonly content: ReactNode;
  readonly title: string;
  readonly routeKey: string;
}

function Shell({ routed }: { routed?: RoutedView | undefined }) {
  const app = usePageApp();
  const worldClient = useWorldClient();
  const route = useParkRoute();
  const quizRoute = useQuizAppRoute();
  const browserRoute = useBrowserRoute();
  const [named, setNamed] = useState<string | null>(null);
  const title =
    named ??
    (routed
      ? routed.title
      : route
        ? PAGE_LABEL[route.page]
        : quizRoute
          ? "Quiz"
          : browserRoute
            ? "Tilo browser"
            : "Not found");
  // A world is a different page per id; the other pages keep focus where it is when only a query changes.
  const routeKey = routed
    ? routed.routeKey
    : route
      ? route.page === "world"
        ? `world/${route.params.id}`
        : route.page
      : quizRoute
        ? `world/${quizRoute.worldId}/app/${quizRoute.artifactId}`
        : browserRoute
          ? `world/${browserRoute.worldId}/browser`
          : "none";
  useLayoutEffect(() => {
    const before = document.title;
    document.title = `${title} · Tilo`;
    return () => {
      document.title = before;
    };
  }, [title]);
  // MOBILE: a phone's status bar takes the nav's colour (the theme's `--card`) for the time the person chose here,
  // not only the system's (index.html names the system's two as the first paint's).
  const root = useRef<HTMLDivElement>(null);
  const theme = themeFor(app.prefs.theme);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the token is re-read when the time or the theme changes
  useEffect(() => {
    const card = root.current
      ? getComputedStyle(root.current).getPropertyValue("--card").trim()
      : "";
    if (!/^#[0-9a-f]{6}$/i.test(card)) return;
    for (const meta of document.querySelectorAll('meta[name="theme-color"]'))
      meta.setAttribute("content", card);
  }, [app.time, theme]);
  const Page = routed ? null : route ? PAGES[route.page] : null;
  const Tour = useParkTour()?.Layer; // ONBOARD-1: the first-run welcome and tour, when the Root provides them
  return (
    <PageTitleContext.Provider value={setNamed}>
      <div
        ref={root}
        data-park
        data-time={app.time}
        data-motion={app.motion}
        data-theme={themeFor(app.prefs.theme)}
      >
        {themeFor(app.prefs.theme) === "studio" ? <DoodleGutter /> : null}
        <AppShell>
          <Suspense fallback={null}>
            {routed ? (
              routed.content
            ) : Page && route?.page === "world" ? (
              <PendingWorldRoute
                key={routeKey}
                worldId={route.params.id ?? ""}
                client={worldClient}
              >
                <Page app={app} />
              </PendingWorldRoute>
            ) : Page ? (
              <Page app={app} />
            ) : quizRoute ? (
              <QuizPlayerPage
                app={app}
                worldId={quizRoute.worldId}
                artifactId={quizRoute.artifactId}
              />
            ) : browserRoute ? (
              <BrowserPage app={app} worldId={browserRoute.worldId} />
            ) : (
              <NotFound go={app.go} />
            )}
            <FocusHeading routeKey={routeKey} />
          </Suspense>
        </AppShell>
        {Tour ? (
          <Suspense fallback={null}>
            <Tour />
          </Suspense>
        ) : null}
      </div>
    </PageTitleContext.Provider>
  );
}

export function ParkApp({ routed }: { routed?: RoutedView | undefined } = {}) {
  // FR-UX-10: the account menu reads the page's real sign-in; null (no sign-in here) keeps the prototype's behaviour.
  const auth = useSessionAuth();
  return (
    <ParkProvider>
      <ParkAuthProvider auth={auth}>
        <Shell routed={routed} />
      </ParkAuthProvider>
    </ParkProvider>
  );
}

export default ParkApp;
