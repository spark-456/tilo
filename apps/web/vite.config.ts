import react from "@vitejs/plugin-react";
import { type Plugin, defineConfig } from "vite";

// The four UI faces main.tsx waits for before it renders (latin subset, woff2). Without a preload
// the browser finds them only after the CSS and the app script have run, one round trip later than
// it could (NFR-01 on a phone: that wait is on the way to the first keystroke).
const PRELOAD_FACES =
  /(nunito-latin-900|nunito-sans-latin-(400|700)|jetbrains-mono-latin-500)-normal-.*\.woff2$/;

function preloadFonts(): Plugin {
  return {
    name: "tilo-preload-fonts",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, ctx) {
        return Object.keys(ctx.bundle ?? {})
          .filter((file) => PRELOAD_FACES.test(file))
          .map((file) => ({
            tag: "link",
            attrs: {
              rel: "preload",
              as: "font",
              type: "font/woff2",
              crossorigin: "",
              href: `/${file}`,
            },
            injectTo: "head-prepend" as const,
          }));
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), preloadFonts()],
  build: {
    // Pixi (about 0.9 MB in two lazy chunks) is fetched after the landing page is interactive
    // (NFR-01), never with it, so the size warning is lifted just above it. No manualChunks: it
    // hoisted shared modules into one Pixi chunk the entry then preloaded in index.html.
    chunkSizeWarningLimit: 1000,
  },
});
