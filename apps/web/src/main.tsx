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
createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
