// SEC-10: where the web client's App Check ids live, and how the app wires them.
//
// `apps/web/src/appcheck/config.ts` exports the two public ids the supervisor recorded (they are public by
// design and are not secrets): FIREBASE_APP_ID (Firebase web app "tilo-web") and RECAPTCHA_SITE_KEY (the
// reCAPTCHA Enterprise score site key). infra/ACCESS.md section 7 records the same two (tests/repo).
// No secret, no model id, no hard-coded debug token anywhere under src/appcheck/ or in the API client.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { FIREBASE_APP_ID, RECAPTCHA_SITE_KEY } from "./config";

const SRC = join(__dirname, "..");
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");
/** Source with comments removed, so a comment may mention what the code must not do. */
const code = (rel: string) =>
  read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

/** Every non-test source file of the App Check folder, plus the two the wiring lives in. */
function appCheckSources(): Array<{ rel: string; text: string }> {
  const dir = join(SRC, "appcheck");
  const rels = existsSync(dir)
    ? readdirSync(dir)
        .filter((f) => /\.(ts|tsx)$/.test(f) && !/\.test\.tsx?$/.test(f))
        .map((f) => `appcheck/${f}`)
    : [];
  return [...rels, "api/http.ts", "api/config.ts", "api/ClientProvider.tsx"].map((rel) => ({
    rel,
    text: read(rel),
  }));
}

describe("SEC-10 the web config holds both public ids", () => {
  it("SEC-10 FIREBASE_APP_ID is the tilo-web web app id", () => {
    expect(FIREBASE_APP_ID).toBe("1:379216745263:web:8cda5846cf882c2cefc7da");
  });

  it("SEC-10 RECAPTCHA_SITE_KEY is the reCAPTCHA Enterprise score site key", () => {
    expect(RECAPTCHA_SITE_KEY).toBe("6LdlsOItAAAAAEhO_aq9zmtbQue6Rni2ZDUDuRTe");
  });

  it("SEC-10 the config file has no model id and no secret-looking value", () => {
    const text = read("appcheck/config.ts");
    expect(text).not.toMatch(/gemini|claude-|gpt-|nemotron|llama/i); // no model id outside config/ (PL-01)
    expect(text).not.toMatch(/AIza[0-9A-Za-z_-]{20,}/); // a Google API key is supplied by the build, not the source
    expect(text).not.toMatch(/GOCSPX-|ya29\.|-----BEGIN/);
  });
});

describe("SEC-10 the wiring reaches the API client", () => {
  it("SEC-10 ClientProvider builds the token getter from the page's host and gives it to chooseClient", () => {
    const text = read("api/ClientProvider.tsx");
    expect(text).toContain("createAppCheckTokenGetter");
    expect(text).toMatch(/window\.location\.hostname|location\.hostname/);
    expect(text).toContain("appCheckToken");
    expect(text).toMatch(/["']\.\.\/appcheck\/appCheck["']/); // static or dynamic import
  });

  it("SEC-10 the host decides whether App Check is local, not import.meta.env.DEV", () => {
    expect(code("appcheck/appCheck.ts")).not.toContain("import.meta.env.DEV"); // tests need the deployed path
  });
});

describe("SEC-10 no secret-looking content", () => {
  it("SEC-10 no API key, private key, OAuth token or hard-coded App Check debug token in the sources", () => {
    for (const { rel, text } of appCheckSources()) {
      expect(text, rel).not.toMatch(/AIza[0-9A-Za-z_-]{20,}/);
      expect(text, rel).not.toMatch(
        /GOCSPX-|ya29\.[0-9A-Za-z_-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY/,
      );
      // `self.FIREBASE_APPCHECK_DEBUG_TOKEN = "<uuid>"` would commit a debug credential.
      expect(text, rel).not.toMatch(
        /FIREBASE_APPCHECK_DEBUG_TOKEN\s*=\s*["'][0-9A-Za-z-]{16,}["']/,
      );
    }
  });

  it("SEC-10 the two public ids appear once, in config.ts, and are not copied into other source files", () => {
    for (const { rel, text } of appCheckSources()) {
      if (rel === "appcheck/config.ts") continue;
      expect(text, rel).not.toContain(FIREBASE_APP_ID);
      expect(text, rel).not.toContain(RECAPTCHA_SITE_KEY);
    }
  });
});
