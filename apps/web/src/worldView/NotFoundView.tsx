// An address Tilo does not know: a world id the client has never heard of. It says so and offers the way back; it
// never shows another world's run in its place (HR-1, HR-4).
import { ViewLink } from "./ViewLink";

export function NotFoundView() {
  return (
    <div className="park-view-root" data-testid="not-found">
      <section className="park-sheet park-view-sheet">
        <h1 className="park-view-title" tabIndex={-1}>
          Not found
        </h1>
        <p className="park-view-note">
          Nothing is at this address, so nothing was changed. Go back to Home to carry on.
        </p>
        <p>
          <ViewLink className="park-view-chiplink" to="/">
            Back to Home
          </ViewLink>
        </p>
      </section>
    </div>
  );
}
