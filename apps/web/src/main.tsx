import "@fontsource/nunito/800.css";
import "@fontsource/nunito/900.css";
import "@fontsource/nunito-sans/400.css";
import "@fontsource/nunito-sans/600.css";
import "@fontsource/nunito-sans/700.css";
import "@fontsource/nunito-sans/800.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import "./styles/app.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

// StrictMode double-invokes effects in dev. The Stage effect tears its
// PixiJS Application down safely even when unmounted mid-init (see
// Stage.tsx), so this is no longer a race and StrictMode's extra checks stay
// on.
const el = document.getElementById("root");
if (!el) throw new Error("#root not found");
const root = el;

// The faces the shell uses load before the first render, so text never swaps
// fonts after it is laid out (no layout shift). If they are slow,
// the shell renders anyway after FONT_WAIT_MS.
const FONT_WAIT_MS = 3000;
const USED_FACES = ["900 16px Nunito", "400 16px 'Nunito Sans'", "700 16px 'Nunito Sans'"];
const fontsReady = Promise.all(USED_FACES.map((face) => document.fonts.load(face))).catch(
  () => undefined,
);
const timeout = new Promise((resolve) => setTimeout(resolve, FONT_WAIT_MS));

Promise.race([fontsReady, timeout]).then(() => {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
