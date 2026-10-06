// Every routed screen at a concrete address on the fixture ids, plus /more. A unit test
// (src/screens/routes.test.ts) fails when a path in screens/meta.ts is missing here, so an
// accessibility sweep over this list covers every screen the app has.
const W = "/world/w_village_basic";
const T = "/task/task_fixture_1";

export const ALL_ROUTES: readonly string[] = [
  "/",
  `${T}/understanding`,
  `${T}/approaches`,
  W,
  `${W}/inspect/B1`,
  "/needs-you",
  "/needs-you/gate",
  "/needs-you/consent",
  "/meeting",
  `${W}/story`,
  `${W}/trace`,
  `${W}/delivery`,
  "/library",
  "/worlds",
  "/autonomy",
  "/channels",
  "/mail",
  "/team",
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
