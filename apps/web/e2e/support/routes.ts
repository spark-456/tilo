// Every routed screen at a concrete address on the fixture ids, plus /more. A unit test
// (src/screens/routes.test.ts) fails when a path in screens/meta.ts is missing here, so an
// accessibility sweep over this list covers every screen the app has.
const W = "/world/w_village_basic";

export const ALL_ROUTES: readonly string[] = [
  "/",
  `${W}/stage`,
  `${W}/inspect/B1`,
  "/needs-you",
  "/needs-you/gate",
  "/needs-you/consent",
  "/meeting",
  `${W}/story`,
  `${W}/trace`,
  `${W}/delivery`,
  "/library",
  "/worlds/replays",
  "/autonomy",
  "/channels",
  "/mail",
  "/team/console",
  "/connections",
  "/library/artifacts",
  "/settings",
  "/estimate",
  "/pilot",
  "/meetings",
  "/plate",
  "/pinboards",
  "/calendar",
  "/more",
];
