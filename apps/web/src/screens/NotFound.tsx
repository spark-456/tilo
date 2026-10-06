// An address Tilo does not know: a world id the client has never heard of, or a path under
// /world/ or /task/ that no screen owns (for example /world/w/inspect/B1/extra). It says so and
// offers the way back; it never shows another world's run in its place (HR-1, HR-4).
import { AppLink } from "./AppLink";

export function NotFound() {
  return (
    <div className="screen-body" data-testid="not-found">
      <h1>Not found</h1>
      <p>Nothing is at this address, so nothing was changed. Go back to Start to carry on.</p>
      <AppLink to="/" className="secondary">
        Back to Start
      </AppLink>
    </div>
  );
}
