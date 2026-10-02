// /screens: the dev-only index of every PRD 18.3 screen (AGW-08), and /more: the production menu
// that reaches every screen the primary navigation does not list. Static; no data, no events.
import { AppLink } from "./AppLink";
import { TAB_SCREEN_IDS } from "./PrimaryNav";
import { SCREENS, type ScreenMeta } from "./meta";

const STATUS_LABEL = { built: "Built", placeholder: "Placeholder", deferred: "Not scheduled" };

export function ScreensIndex() {
  return (
    <div className="screen-body" data-testid="screens-index">
      <h1>Screens</h1>
      <p>
        Dev-only index of the PRD 18.3 screens. All data is fixture data from the fixture client.
        Open the app with <code>?speed=20</code> to fast-forward the recorded fixture replay.
      </p>
      <table className="screen-table">
        <caption>Every screen, its priority and whether it is built</caption>
        <thead>
          <tr>
            <th scope="col">ID</th>
            <th scope="col">Screen</th>
            <th scope="col">Priority</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {SCREENS.map((s) => (
            <tr key={s.id} data-screen-id={s.id} data-status={s.status}>
              <td>{s.id}</td>
              <td>{s.path === null ? s.name : <AppLink to={s.path}>{s.name}</AppLink>}</td>
              <td>{s.priority}</td>
              <td>{STATUS_LABEL[s.status]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The screens the primary navigation does not open itself. */
const moreScreens = (): ScreenMeta[] =>
  SCREENS.filter((s) => s.path !== null && !TAB_SCREEN_IDS.has(s.id));

export function More() {
  return (
    <div className="screen-body" data-testid="more-menu">
      <h1>More</h1>
      <ul className="screen-list">
        {moreScreens().map((s) => (
          <li key={s.id}>
            <AppLink to={s.path ?? "/"}>{s.name}</AppLink>
            {s.status === "placeholder" && <span className="screen-tag"> Coming soon</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
