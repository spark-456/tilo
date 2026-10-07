import "@fontsource/nunito/900.css";
import "@fontsource/nunito-sans/400.css";
import "@fontsource/nunito-sans/700.css";
import "@fontsource/jetbrains-mono/500.css";
import "./park/tokens/fonts";
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
// The Park shell's other three faces (its fonts are declared here too, tokens/fonts) are fetched now, beside the
// app chunks, not after the shell's first commit: the shell stays hidden under its splash until they are in, and
// asking late put them on the landing's critical path (NFR-01). Only a Park path asks; nothing waits for them here.
const parkFaces = ["800 1em 'Nunito'", "600 1em 'Nunito Sans'", "800 1em 'Nunito Sans'"];
const fonts = [
  "900 1em 'Nunito'",
  "400 1em 'Nunito Sans'",
  "700 1em 'Nunito Sans'",
  "500 1em 'JetBrains Mono'",
  ...(isParkPath(window.location.pathname) ? parkFaces : []),
].map((f) => document.fonts.load(f).catch(() => undefined)); // a face that fails to load must not be an uncaught rejection
if (isParkPath(window.location.pathname)) render();
else Promise.all(fonts).then(render); // each face has its own catch above
