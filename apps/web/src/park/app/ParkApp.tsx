// The Park app (README "Routes", "The `app` prop", "Focus"): the data-park root around the shell (shell/AppShell:
// nav, backdrop, the one <main>, toast, world loader), the page for the route, the document title and the
// focus move after a route change. Lazy-imported by src/Root.tsx, so a landing visit never loads it (NFR-01).
import { AppShell } from "../shell/AppShell";
import { ParkAuthProvider } from "../shell/auth";
import { useParkTour } from "../shell/tour";
import "../tokens/fonts";
import "../tokens/park.css";
import "../tokens/themes.css";
import { themeFor } from "../tokens/themes";
import { PAGE_LABEL } from "./AppCtx";
import { NotFound } from "./NotFound";
import "./park-app.css";
import { ParkProvider, usePageApp, useSessionAuth } from "./context";
import { PageTitleContext } from "./pageTitle";
import { PAGES } from "./pages";
import { isHomeAddress, useParkRoute, useQuizAppRoute } from "./router";

const QuizPlayerPage = lazy(() =>
  import("../pages/QuizPlayer/QuizPlayerPage").then((m) => ({ default: m.QuizPlayerPage })),
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
  const route = useParkRoute();
  const quizRoute = useQuizAppRoute();
  // A world is a different page per id; the other pages keep focus where it is when only a query changes.
  const routeKey = routed
    ? routed.routeKey
    : route
      ? route.page === "world"
        ? `world/${route.params.id}`
        : route.page
      : quizRoute
        ? `world/${quizRoute.worldId}/app/${quizRoute.artifactId}`
        : "none";
  useEffect(() => {
    const before = document.title;
    document.title = `${title} · Tilo`;
    return () => {
      document.title = before;
    };
  }, [title]);
  const Page = routed ? null : route ? PAGES[route.page] : null;
  const Tour = useParkTour()?.Layer; // ONBOARD-1: the first-run welcome and tour, when the Root provides them
  return (
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
