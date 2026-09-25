import { useMediaQuery } from "./hooks/useMediaQuery";
import { Stage } from "./stage/Stage";

// World is the only screen that exists yet (PRD 5.5). Stage mode is a display setting (PRD 9.6).
const Nav = ({ id }: { id: string }) => (
  <nav className={id} data-testid={id} aria-label="Primary">
    <button type="button" className="nav-btn" aria-current="page">
      World
    </button>
  </nav>
);
const stageMode = new URLSearchParams(window.location.search).get("display") === "stage";

/** PRD 18.3 layout frame: desktop rails either side of the stage; mobile bottom tabs. */
export function App() {
  const mobile = useMediaQuery("(max-width: 767px)");
  return (
    <div className="app-shell" data-stage-mode={stageMode ? "on" : "off"}>
      {!mobile && <Nav id="left-rail" />}
      <Stage />
      {mobile ? (
        <Nav id="bottom-tabs" />
      ) : (
        <aside className="right-rail" data-testid="right-rail">
          <h2>Activity</h2>
          <p data-testid="right-rail-meter">Nothing yet. This fills in once a run starts.</p>
          <h2>Needs you</h2>
          <p>Nothing needs you.</p>
          <h2>Roster</h2>
          <p>No agents assigned.</p>
        </aside>
      )}
    </div>
  );
}
