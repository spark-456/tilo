import react from "@vitejs/plugin-react";
import { type Plugin, defineConfig } from "vite";

// The universal UI faces used immediately on every page (latin subset, woff2). Preloading only
// universally rendered faces avoids Chrome's unused preload warning on SPA routes (#738).
const PRELOAD_FACES = /(nunito-sans-latin-(400|700))-normal-.*\.woff2$/;

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
