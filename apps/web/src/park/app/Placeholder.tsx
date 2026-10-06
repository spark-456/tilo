// The page every route shows until its real page is plugged into pages.ts. It prints the route it got,
// so a lane can see its page is wired before it builds it. The <main> landmark belongs to the shell.
import { PageSheet } from "../components";
import { type AppCtx, PAGE_LABEL } from "./AppCtx";

export default function Placeholder({ app }: { app: AppCtx }) {
  const given = Object.entries(app.params);
  return (
    <div data-testid={`park-page-${app.page}`}>
      <PageSheet>
        <h1 className="park-app__title" tabIndex={-1}>
          {PAGE_LABEL[app.page]}
        </h1>
        <p className="park-app__note">Not built yet</p>
        {given.length > 0 ? (
          <p className="park-app__note">{given.map(([k, v]) => `${k}: ${v}`).join(", ")}</p>
        ) : null}
      </PageSheet>
    </div>
  );
}
