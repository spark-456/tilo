// The addresses the OLD app owns (WEB-CUTOVER): the intake at /start, the task and stage screens and every
// other kept screen. `src/Root.tsx` shows the old app for these and the Park app for everything else, so an
// address no screen owns reaches the Park "Page not found" instead of the old Start screen. A trailing slash is
// tolerated, as in the patterns of screens/meta.ts and screens/routes.tsx. Dependency-free on purpose: Root is
// the entry chunk, and importing meta.ts or routes.tsx here would put the old app back into the landing bundle.
// `keptPaths.test.ts` checks this list against screens/meta.ts and the flow routes.
const KEPT: readonly RegExp[] = [
  /^\/start\/?$/,
  /^\/task\/[^/]+\/(?:understanding|approaches)\/?$/,
  /^\/world\/[^/]+\/(?:stage|story|trace|delivery)\/?$/,
  /^\/world\/[^/]+\/inspect\/[^/]+\/?$/,
  /^\/needs-you(?:\/(?:gate|consent))?\/?$/,
  /^\/(?:meeting|autonomy|channels|mail|connections|settings|estimate|pilot)\/?$/,
  /^\/(?:plate|pinboards|calendar|more)\/?$/,
  /^\/library(?:\/artifacts)?\/?$/,
  /^\/meetings(?:\/[^/]+)?\/?$/,
  /^\/worlds\/replays\/?$/,
  /^\/team\/console\/?$/,
  // dev only, as in screens/routes.tsx: the screens index, the cards gallery and the component sheet
  ...(import.meta.env.DEV ? [/^\/screens(?:\/cards)?\/?$/, /^\/dev\/components\/?$/] : []),
];

/** True when the old app owns this address (`window.location.pathname`). */
export const isKeptPath = (pathname: string): boolean => KEPT.some((re) => re.test(pathname));
