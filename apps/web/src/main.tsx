import { installBootCover } from "./bootCover";

// Let the HTML-only cover paint before loading app code, fonts, or the application stylesheet: the cover artwork
// is decoded first, then one task yields to the browser. No frame loop is used (honesty rules, FR-WLD-09).
const afterFirstPaint = (decoded: Promise<void>) =>
  decoded.then(() => new Promise<void>((resolve) => window.setTimeout(resolve, 0)));

void afterFirstPaint(installBootCover())
  .then(() => import("./startApp"))
  .then(() => import("./staleBuild"))
  .then((stale) => stale.watchForNewBuild());
