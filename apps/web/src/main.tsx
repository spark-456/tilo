import "@fontsource/nunito/800.css";
import "@fontsource/nunito/900.css";
import "@fontsource/nunito-sans/400.css";
import "@fontsource/nunito-sans/600.css";
import "@fontsource/nunito-sans/700.css";
import "@fontsource/nunito-sans/800.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
import "./styles/app.css";

import { createRoot } from "react-dom/client";
import { App } from "./App";

// No React.StrictMode: it double-invokes effects in dev, which would race two
// PixiJS Applications against the same WebGL canvas on mount.
const el = document.getElementById("root");
if (!el) throw new Error("#root not found");
createRoot(el).render(<App />);
