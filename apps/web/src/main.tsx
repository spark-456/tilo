import "@fontsource/nunito/900.css";
import "@fontsource/nunito-sans/400.css";
import "@fontsource/nunito-sans/700.css";
import "@fontsource/jetbrains-mono/500.css";
import "./styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Root } from "./Root";
import { initDensity } from "./display/density";

initDensity(); // the saved display mode is on <html> before the first paint

// Render once the UI faces load, so text never reflows (no layout shift).
const root = createRoot(document.getElementById("root") as HTMLElement);
const fonts = [
  "900 1em 'Nunito'",
  "400 1em 'Nunito Sans'",
  "700 1em 'Nunito Sans'",
  "500 1em 'JetBrains Mono'",
].map((f) => document.fonts.load(f));
Promise.all(fonts)
  .catch(() => undefined)
  .then(() =>
    root.render(
      <StrictMode>
        <Root />
      </StrictMode>,
    ),
  );
