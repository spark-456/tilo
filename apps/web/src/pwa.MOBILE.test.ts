// MOBILE (PWA): Tilo installs to a phone's home screen (Chrome's installability: a linked manifest with a name, a
// start_url, display standalone and 192/512 icons; iOS: an apple-touch-icon and the web-app meta tags), and a deploy
// still reaches every phone at once: nothing in front of the network may keep index.html or an API answer. The page
// and "/" are no-cache, only the hashed /assets/* (and /loader/*) are immutable, and no service worker handles fetch or
// opens Cache Storage (the one worker, push-sw.js, shows notices only; staleBuild.ts reloads an old tab).
import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";

const web = (p: string) => new URL(`../${p}`, import.meta.url);
const html = readFileSync(web("index.html"), "utf8");
const manifest = JSON.parse(readFileSync(web("public/manifest.webmanifest"), "utf8")) as {
  name: string;
  short_name: string;
  start_url: string;
  scope: string;
  id: string;
  display: string;
  theme_color: string;
  background_color: string;
  icons: { src: string; sizes: string; type: string; purpose: string }[];
};
const studio = JSON.parse(readFileSync(web("../../config/themes/studio.json"), "utf8")) as {
  day: Record<string, string>;
  night: Record<string, string>;
};
const firebase = JSON.parse(readFileSync(web("../../firebase.json"), "utf8")) as {
  hosting: { headers: { source: string; headers: { key: string; value: string }[] }[] };
};

/** Width and height from a PNG's IHDR chunk. */
function pngSize(path: string): [number, number] {
  const bytes = readFileSync(web(`public${path}`));
  expect(bytes.subarray(1, 4).toString("ascii")).toBe("PNG");
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

const cacheFor = (source: string): string | undefined =>
  firebase.hosting.headers
    .filter((h) => h.source === source)
    .flatMap((h) => h.headers)
    .find((h) => h.key === "Cache-Control")?.value;

describe("MOBILE_PWA the manifest", () => {
  it("MOBILE_PWA_manifest_is_installable_and_linked", () => {
    expect(html).toContain('<link rel="manifest" href="/manifest.webmanifest" />');
    expect(manifest).toMatchObject({
      id: "/",
      name: "Tilo",
      short_name: "Tilo",
      start_url: "/",
      scope: "/",
      display: "standalone",
    });
    expect(manifest.short_name.length).toBeLessThanOrEqual(12); // never cut under a home-screen icon
  });

  it("MOBILE_PWA_colours_come_from_the_design_tokens", () => {
    // the bar and the splash match the Studio nav (card) and the white boot cover the app opens on
    expect(manifest.theme_color.toUpperCase()).toBe(studio.day.card?.toUpperCase());
    expect(manifest.background_color.toUpperCase()).toBe("#FFFFFF");
    expect(html).toContain(
      `<meta name="theme-color" content="${studio.day.card}" media="(prefers-color-scheme: light)" />`,
    );
    expect(html).toContain(
      `<meta name="theme-color" content="${studio.night.card}" media="(prefers-color-scheme: dark)" />`,
    );
  });

  it("MOBILE_PWA_icons_192_512_and_maskable_exist_at_their_stated_size", () => {
    for (const size of [192, 512])
      for (const purpose of ["any", "maskable"]) {
        const icon = manifest.icons.find(
          (i) => i.sizes === `${size}x${size}` && i.purpose === purpose,
        );
        expect(icon, `${size} ${purpose}`).toBeDefined();
        expect(icon?.type).toBe("image/png");
        expect(pngSize(icon?.src ?? "")).toEqual([size, size]);
      }
  });

  it("MOBILE_PWA_ios_home_screen_tags", () => {
    const touch = /<link rel="apple-touch-icon" href="([^"]+)" \/>/.exec(html)?.[1] ?? "";
    expect(pngSize(touch)).toEqual([180, 180]);
    // Chrome warns about the Apple tag alone, so the standard one sits beside it
    expect(html).toContain('<meta name="mobile-web-app-capable" content="yes" />');
    expect(html).toContain('<meta name="apple-mobile-web-app-capable" content="yes" />');
    expect(html).toContain('<meta name="apple-mobile-web-app-title" content="Tilo" />');
  });

  it("MOBILE_keyboard_lifts_fixed_panels_and_zoom_stays_allowed", () => {
    const viewport = /name="viewport"\s+content="([^"]+)"/.exec(html)?.[1] ?? "";
    // Chrome on Android shrinks the layout with the keyboard, so a fixed panel's input (the Tilo bubble) stays above it
    expect(viewport).toBe(
      "width=device-width, initial-scale=1.0, interactive-widget=resizes-content",
    );
    expect(viewport).not.toMatch(/maximum-scale|user-scalable/); // pinch zoom is the person's (WCAG 1.4.4)
  });
});

describe("MOBILE_PWA a deploy reaches phones at once", () => {
  it("MOBILE_PWA_index_html_and_root_are_never_cached", () => {
    expect(cacheFor("/")).toBe("no-cache");
    expect(cacheFor("/index.html")).toBe("no-cache");
    expect(cacheFor("**")).toBe("no-cache"); // the manifest, the icons and every other path revalidate
    expect(cacheFor("/assets/**")).toMatch(/immutable/); // hashed names only
    for (const h of firebase.hosting.headers) {
      const value = h.headers.find((x) => x.key === "Cache-Control")?.value ?? "";
      if (/max-age=[1-9]|immutable/.test(value))
        expect(["/assets/**", "/loader/**"], h.source).toContain(h.source);
    }
  });

  it("MOBILE_PWA_no_service_worker_answers_fetches_or_keeps_a_cache", () => {
    const scripts = readdirSync(web("public"), { recursive: true, encoding: "utf8" })
      .map((f) => f.replaceAll("\\", "/"))
      .filter((f) => f.endsWith(".js"));
    expect(scripts.length).toBeGreaterThan(0);
    for (const f of scripts) {
      const code = readFileSync(web(`public/${f}`), "utf8");
      // A worker that answers fetches could hand a phone yesterday's index.html or an API answer; if one is ever
      // needed it must be network-first for navigations and cache only hashed /assets/*, and this test changes with it.
      expect(code, f).not.toMatch(/addEventListener\(\s*["']fetch["']|onfetch\s*=/);
      expect(code, f).not.toMatch(/\bcaches\s*\.|CacheStorage|importScripts/);
    }
  });
});
