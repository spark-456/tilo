// The "Page not found" page: an address that is no page of the app, or a world id the app does not know (QA-DEMO-1
// M2). Shared by ParkApp (an unknown route) and the World page (an unknown id), so neither shows another job.
import type { MouseEvent } from "react";
import { PageSheet } from "../components";
import type { AppCtx } from "./AppCtx";

export const NOT_FOUND_TITLE = "Page not found";

export function NotFound({ go }: { go: AppCtx["go"] }) {
  const open = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    go("home");
  };
  return (
    <div data-testid="park-not-found">
      <PageSheet>
        <h1 className="park-app__title" tabIndex={-1}>
          {NOT_FOUND_TITLE}
        </h1>
        <p className="park-app__note">There is no page at this address.</p>
        <a className="park-app__link" href="/" onClick={open}>
          Go to Home
        </a>
      </PageSheet>
    </div>
  );
}
