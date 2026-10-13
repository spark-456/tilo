import { execSync } from "node:child_process";
import react from "@vitejs/plugin-react";
import { type Plugin, defineConfig } from "vite";

// QA-DEMO-1 m12: the commit this bundle was built from, so a deployed page can be told from an older build. A hex
// sha only (never a branch, a path or a secret): `TILO_BUILD_SHA` or a CI commit variable, else `git rev-parse`.
function buildSha(): string {
  const fromEnv = process.env.TILO_BUILD_SHA ?? process.env.COMMIT_SHA ?? process.env.GITHUB_SHA;
  const raw = fromEnv?.trim() ?? "";
  if (/^[0-9a-f]{7,40}$/i.test(raw)) return raw.toLowerCase();
  try {
    const out = execSync("git rev-parse HEAD", { stdio: ["ignore", "pipe", "ignore"] });
    const sha = out.toString().trim();
    return /^[0-9a-f]{7,40}$/i.test(sha) ? sha : "unknown";
  } catch {
    return "unknown";
  }
}
const BUILD_SHA = buildSha();

/** `<meta name="tilo-build">` in the page head, in the dev server and in the build. */
function buildStamp(): Plugin {
  return {
    name: "tilo-build-stamp",
    transformIndexHtml: () => [
      { tag: "meta", attrs: { name: "tilo-build", content: BUILD_SHA }, injectTo: "head" as const },
    ],
  };
}

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
  plugins: [react(), preloadFonts(), buildStamp()],
  define: { __TILO_BUILD_SHA__: JSON.stringify(BUILD_SHA) },
  build: {
    // Pixi (about 0.9 MB in two lazy chunks) is fetched after the landing page is interactive
    // (NFR-01), never with it, so the size warning is lifted just above it. No manualChunks: it
    // hoisted shared modules into one Pixi chunk the entry then preloaded in index.html.
    chunkSizeWarningLimit: 1000,
  },
});
