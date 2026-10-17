import { installBootCover } from "./bootCover";

installBootCover();

// Let the HTML-only cover paint before loading app code, fonts, or the application stylesheet.
const afterFirstPaint = () =>
  new Promise<void>((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );

void afterFirstPaint().then(() => import("./startApp"));
