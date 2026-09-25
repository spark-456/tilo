import { useMediaQuery } from "./hooks/useMediaQuery";
import { Stage } from "./stage/Stage";

// The World screen is the only one that exists yet (PRD 5.5), so it is always
// the current one — hence the permanent `aria-current="page"` (PRD 17.5) and
// the selected-pill styling (design exports show the active nav item this
// way, not centred and unmarked).
const NavButton = () => (
  <button type="button" className="nav-btn nav-btn--active" aria-current="page">
    World
  </button>
);

/** PRD 18.3 "Screens": the layout frame. Desktop gets a 72px left rail, centre
 * stage and 360px right rail; mobile gets bottom tabs and no side rails. Ships
 * only navigation for screens that exist (PRD 5.5) — just the World. */
export function App() {
  const isMobile = useMediaQuery("(max-width: 767px)");

  return (
    <div className="app-shell">
      {/* Visually hidden: gives the page a single top-level heading (axe
          "page-has-heading-one") without adding a header bar the design
          exports don't cover. */}
      <h1 className="visually-hidden">Tilo — World</h1>
      {!isMobile && (
        <nav className="left-rail" data-testid="left-rail" aria-label="Primary">
          <span className="brand-mark" aria-hidden="true">
            T
          </span>
          <NavButton />
        </nav>
      )}
      <Stage />
      {!isMobile && (
        <aside className="right-rail" data-testid="right-rail">
          <h2>Activity</h2>
          {/* PRD 18.3 "honest empty states only (no fake numbers)": nothing
              is shown until events exist. */}
          <p className="right-rail-meter" data-testid="right-rail-meter">
            Nothing to show yet — this fills in once the run starts.
          </p>
          <h2>Needs you</h2>
          <p className="empty">Nothing needs you yet.</p>
          <h2>Roster</h2>
          <p className="empty">No agents assigned yet.</p>
        </aside>
      )}
      {isMobile && (
        <nav className="bottom-tabs" data-testid="bottom-tabs" aria-label="Primary">
          <NavButton />
        </nav>
      )}
    </div>
  );
}
