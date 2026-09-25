import { useMediaQuery } from "./hooks/useMediaQuery";
import { Stage } from "./stage/Stage";

const NavButton = () => (
  <button type="button" className="nav-btn">
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
      {!isMobile && (
        <nav className="left-rail" data-testid="left-rail" aria-label="Primary">
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
