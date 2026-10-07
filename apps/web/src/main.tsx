import "@fontsource/nunito/900.css";
import "@fontsource/nunito-sans/400.css";
import "@fontsource/nunito-sans/700.css";
import "@fontsource/jetbrains-mono/500.css";
import "./styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Root } from "./Root";
import { initDensity } from "./display/density";
import { isParkPath } from "./park/app/router";

initDensity(); // the saved display mode is on <html> before the first paint

// Render once the UI faces load, so text never reflows (no layout shift). The Park app renders at once: its boot
// splash is what waits for the fonts (README Boot), and the shell stays hidden under it until they are in.
const root = createRoot(document.getElementById("root") as HTMLElement);
const render = () =>
  root.render(
    <StrictMode>
      <Root />
    </StrictMode>,
  );
const fonts = [
  "900 1em 'Nunito'",
  "400 1em 'Nunito Sans'",
  "700 1em 'Nunito Sans'",
  "500 1em 'JetBrains Mono'",
].map((f) => document.fonts.load(f).catch(() => undefined)); // a face that fails to load must not be an uncaught rejection
if (isParkPath(window.location.pathname)) render();
else
  Promise.all(fonts)
    .catch(() => undefined)
    .then(render);
