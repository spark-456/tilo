// QA-DEMO-1 m12: the short commit sha this bundle was built from (vite.config.ts `define`), shown in the Home footer
// and in <meta name="tilo-build">. A short hex string, no branch, path or secret; "dev" where no build defined it
// (the unit tests).
declare const __TILO_BUILD_SHA__: string | undefined;

export const BUILD_SHA: string =
  typeof __TILO_BUILD_SHA__ === "string" && /^[0-9a-z]{3,40}$/.test(__TILO_BUILD_SHA__)
    ? __TILO_BUILD_SHA__
    : "dev";
