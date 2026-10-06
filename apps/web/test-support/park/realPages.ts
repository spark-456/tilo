// The pages that have a real implementation. A page lane adds its id here in the PR that replaces the
// Placeholder in `park/app/pages.ts`; the WEB-3a tests that assume "this page is a Placeholder" then skip it,
// while the generic checks (route resolves, one main, an h1, the title, `data-testid="park-page-<id>"`) keep
// covering every page.
import { PAGE_IDS, type PageId } from "../../src/park/app/AppCtx";

export const REAL_PAGES: readonly PageId[] = ["home", "connectors"];

export const PLACEHOLDER_PAGES: readonly PageId[] = PAGE_IDS.filter(
  (id) => !REAL_PAGES.includes(id),
);
