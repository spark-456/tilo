import "@fontsource/nunito/900.css";
import "@fontsource/nunito-sans/400.css";
import "@fontsource/nunito-sans/700.css";
import "@fontsource/jetbrains-mono/500.css";
import "./styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

// Render once the UI faces load, so text never reflows (no layout shift).
const root = createRoot(document.getElementById("root") as HTMLElement);
const fonts = ["400 1em 'Nunito Sans'", "700 1em 'Nunito Sans'"].map((f) => document.fonts.load(f));
Promise.all(fonts)
  .catch(() => undefined)
  .then(() =>
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    ),
  );
