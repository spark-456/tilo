// The static body of every screen that is not built yet (PRD 18.3). It claims no progress and
// shows no data (HR-1 to HR-7): it only says what the screen is and that it is not built.
import { AppLink } from "./AppLink";
import { screenMeta } from "./meta";

export function ComingSoon({ id }: { id: string }) {
  const meta = screenMeta(id);
  return (
    <div className="screen-body" data-testid="coming-soon" data-screen-id={id}>
      <h1>{meta?.name ?? id}</h1>
      <p className="screen-tag">
        {id} · {meta?.priority ?? "Must"} · Coming soon
      </p>
      <p>
        This screen is not built yet. Nothing on it is real, and nothing here is running. It is part
        of the Tilo plan (pillar {meta?.pillar ?? "unknown"}).
      </p>
      <AppLink to="/" className="secondary">
        Back to Start
      </AppLink>
    </div>
  );
}
